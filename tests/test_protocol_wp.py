"""Protocol tests for the "WP" firmware family (Guardian / D5 V2 power stations).

protocol.py has no Home Assistant imports, so this file runs both under pytest
and standalone:

    python tests/test_protocol_wp.py

Everything here is built from synthetic packets; no captures from a real device.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble")
)

import protocol  # noqa: E402

TLV_TAG = 0x02
TLV_LEN = 0x05


def tlv(dpid: int, value: int) -> bytes:
    """One packed telemetry entry: [0x02][0x05][dpid][uint32 little-endian]."""
    return bytes([TLV_TAG, TLV_LEN, dpid]) + (value & 0xFFFFFFFF).to_bytes(4, "little")


def wp_frames(payload: bytes, prefix: int = 0x03) -> list[bytearray]:
    """Chunk a TLV payload into 20-byte notifications the way the station does.

    Frames are ``[prefix][pkgSn][17 payload bytes][CRC8-SMBUS]`` where pkgSn holds
    the packet index in its low 7 bits and the "last packet" flag in bit 7.  The
    final frame is zero padded, which is what lets the parser tell a finished
    stream from a truncated one.
    """
    chunks = [payload[i : i + 17] for i in range(0, len(payload), 17)] or [b""]
    frames = []
    for idx, chunk in enumerate(chunks):
        frame = bytearray(20)
        frame[0] = prefix
        frame[1] = idx | (0x80 if idx == len(chunks) - 1 else 0)
        frame[2 : 2 + len(chunk)] = chunk
        frame[19] = protocol._crc8(bytes(frame[:19]))
        frames.append(frame)
    return frames


def auth_body(frames: list[bytearray]) -> bytes:
    """Reassemble the config-net-info payload from its frames (minus terminator)."""
    return b"".join(bytes(frame[2:19]) for frame in frames[:-1])


# -- AUTH / config-net-info ---------------------------------------------------


def test_auth_frame_layout() -> None:
    frames = protocol.build_config_net_info("abcde12345", open_id="oTest", user_id=42)
    # 169 payload bytes -> 10 frames, plus the 0x89 terminator frame
    assert len(frames) == 11, len(frames)
    assert all(len(f) == 20 for f in frames)
    assert frames[-1][1] == 0x89, "terminator frame must use index 0x89"

    body = auth_body(frames)
    assert body[0] == 0x01, "payload starts with the config header byte"
    assert body[1] == 0xA8, "length byte is 0xA8 = 168 bytes of fields"
    assert body[104:114] == b"abcde12345", "device key field"
    assert body[114:147] == b"oTest".ljust(33, b"\x00"), "openId field"
    assert int.from_bytes(body[165:170], "big") == 42, "userId field, 5 bytes big-endian"


def test_empty_ssid_is_padded_with_0x01_not_0x02() -> None:
    """The pad byte that decides whether the station accepts the AUTH frame.

    With 0x02 the station answers 03 80 01 01 01 and drops the link; only 0x01 is
    accepted for an empty SSID field.  Locked down here because the difference is
    a single byte that looks harmless in a capture.
    """
    body = auth_body(protocol.build_config_net_info("abcde12345", open_id="o", user_id=1))
    assert body[2:34] == b"\x01" * 32
    assert body[2:34] != b"\x02" * 32


def test_populated_ssid_is_zero_padded() -> None:
    body = auth_body(
        protocol.build_config_net_info("abcde12345", open_id="o", user_id=1, ssid="homeap")
    )
    assert body[2:34] == b"homeap".ljust(32, b"\x00")


def test_frames_are_crc_sealed() -> None:
    for frame in protocol.build_config_net_info("abcde12345", open_id="o", user_id=1):
        assert frame[19] == protocol._crc8(bytes(frame[:19]))


def test_legacy_tt_auth_is_byte_identical() -> None:
    """Stations that do not pass an identity must get the original sequence.

    The WiFi-provisioning variant embeds a freshly generated token, so only its
    deterministic frames are compared.
    """
    for key in ("bd236b1695", "0123456789"):
        assert protocol.build_init_sequence(key) == protocol._build_init_sequence_legacy(key)

        new = protocol.build_init_sequence(key, ssid="ap", psk="secret")
        old = protocol._build_init_sequence_legacy(key, ssid="ap", psk="secret")
        assert len(new) == len(old)
        for i, (a, b) in enumerate(zip(new, old)):
            if i == 6:  # deterministic headers + key, then the token starts
                assert a[:14] == b[:14], i
            elif i in (7, 8):  # frames that are nothing but token
                assert a[:2] == b[:2] and len(a) == len(b), i
            else:
                assert a == b, i


def test_identity_selects_config_net_info() -> None:
    assert protocol.build_init_sequence(
        "abcde12345", open_id="oTest", user_id=42
    ) == protocol.build_config_net_info("abcde12345", open_id="oTest", user_id=42)


# -- packed telemetry ---------------------------------------------------------


def test_packed_dc_inputs_are_split() -> None:
    """attr 23 holds both DC inputs as two uint16 halves; the sum is the real power.

    1999 W + 2001 W = 4000 W, which is what attr 21 (total input) reports in the
    same stream.  Decoded as one uint32 the field would read 131,071,479 W.
    """
    payload = (
        tlv(3, 87)  # battery %, several leading entries so later TLVs straddle
        + tlv(21, 4000)  # total input power
        + tlv(22, 0)  # grid input
        + tlv(23, (2001 << 16) | 1999)  # both DC inputs packed
        + tlv(32, 860)
    )
    out = protocol.parse_packet_sequence(wp_frames(payload))
    assert out[3] == 87
    assert out[21] == 4000
    assert out[23] == 4000, "aggregate must stay under attr 23"
    assert out[2301] == 1999, "low half = DC input 1"
    assert out[2302] == 2001, "high half = DC input 2"
    assert out[2301] + out[2302] == out[21]


def test_entries_straddling_packet_boundaries_decode() -> None:
    """7-byte entries cannot align with 17-byte payload slices; check the tail."""
    payload = (
        tlv(3, 98)
        + tlv(4, 878)
        + tlv(21, 2403)
        + tlv(22, 0)
        + tlv(23, (1210 << 16) | 1193)
    )
    frames = wp_frames(payload)
    assert len(frames) > 1, "test needs a multi-packet stream"
    out = protocol.parse_packet_sequence(frames)
    assert out[23] == 2403 == out[21]
    assert (out[2301], out[2302]) == (1193, 1210)


def test_fallback_split_only_fires_on_impossible_wattage() -> None:
    """The post-parse guard must leave ordinary wattages alone.

    The same field can reach the caller through the compact or 0x0A-tagged readers
    as one little-endian uint32, and those parsers know nothing about the packing,
    so _split_packed_power() is applied to their output as well.  It must never
    touch a value that could be a real wattage.
    """
    for watts in (0, 1, 4000, 6000, 65535):
        out = protocol._split_packed_power({23: watts})
        assert out == {23: watts}, watts
    out = protocol._split_packed_power({23: 65536})
    assert out == {23: 1, 2301: 0, 2302: 1}, out


def test_wp_stream_aggregate_is_right_for_small_values() -> None:
    """Inside a WP stream the halves are always unpacked; the sum is invariant.

    A small uint32 simply means the second input was idle (high half zero), so the
    aggregate under attr 23 is unchanged either way.
    """
    for watts in (0, 1, 4000, 65535):
        out = protocol.parse_packet_sequence(wp_frames(tlv(23, watts)))
        assert out[23] == watts, watts


def test_split_is_idempotent() -> None:
    once = protocol._split_packed_power({23: (1210 << 16) | 1193})
    assert once == {23: 2403, 2301: 1193, 2302: 1210}
    assert protocol._split_packed_power(dict(once)) == once


def test_tt_shaped_stream_is_left_to_the_legacy_parsers() -> None:
    """A 0x0A-tagged telemetry packet must not be mistaken for a WP stream."""
    tt = bytearray(20)
    tt[0] = 0x01
    tt[1] = 0x80  # index 0, last packet
    tt[2:7] = bytes([0x0A, 0x03, 0x03, 87, 0x00])
    tt[19] = protocol._crc8(bytes(tt[:19]))
    assert protocol._wp_looks_like([tt]) is False
    assert protocol.parse_ble_packet(tt) == protocol._parse_ble_packet_impl(tt)


def test_expansion_count_follows_reported_slots() -> None:
    """Mirrors the sensor-side derivation: only slots carrying data are counted."""
    try:
        from sensor import _derive_ext_count
    except ImportError:
        return  # sensor.py needs Home Assistant on sys.path; skipped outside HA
    assert _derive_ext_count({0: {79: 100}, 1: {79: 98}}) == 2
    assert _derive_ext_count({0: {79: 100}, 1: {79: 98}, 2: {79: 95}}) == 3
    assert _derive_ext_count({0: {79: 100}, 1: {}}) == 1
    assert _derive_ext_count({1: {}}) is None  # coordinator's pre-seed only
    assert _derive_ext_count(None) is None


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print("\nsome tests failed" if failed else "\nall tests passed")
    raise SystemExit(1 if failed else 0)
