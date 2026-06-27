#!/usr/bin/env python3
"""
ble_confignet.py - Provision WiFi onto an OUPES (DoHome ESP32) device over BLE,
using the REAL packet format decoded from the Cleanergy APK v1.4.2
(SingleBleDevice.getBleToDeviceSendConfigNetInfoCmd1 + BlePackage.reqCmdToPkg).

This supersedes pair_device.py --ssid / provision_wifi.py, whose WiFi packet
format was an unverified guess. A WiFi packet capture proved the app uses NO
SmartConfig/ESP-Touch/AirKiss; credentials are delivered over BLE in this
"config-net Cmd1" command.

Command hex string (normal "TT" device, non-"WP"):
  "01"                         cmd 0x01
  + len(1B)                    0x99 (no domain) / 0xA3 (with domain)
  + ssid   -> 32 bytes  (UTF-8, right zero-padded; empty -> 0x02*32)
  + passwd -> 64 bytes  (UTF-8, right zero-padded)
  + bssid  -> 6 bytes   (AP MAC, no colons; or 000000000000)
  + deviceKey -> 10 bytes  (ASCII of the key string)
  + openId -> 33 bytes  (ASCII binding token, right zero-padded; zeros ok)
  + lat(4B=0) + lng(4B=0)
  + [domain -> 10 bytes, only if --domain given]

Framing: split hex into 17-byte (34 hex) chunks; each BLE packet =
  [0x01][pkgSn][17 data bytes][crc8],  pkgSn = index, with 0x80 OR'd on the LAST.
  crc8 = poly 0x07 MSB-first over the first 19 bytes. Write to char 00002b11.

Usage:
  python ble_confignet.py 8C:D0:B2:A9:8C:59 --ssid 170PSD-IoT --psk 00100110 \
      --key 39e0219ad0 --bssid <AP_BSSID_optional>

Then watch your router DHCP leases for the device's WiFi MAC.
"""
import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

WRITE_CHAR = "00002b11-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR = "00002b10-0000-1000-8000-00805f9b34fb"


def crc8(data: bytes) -> int:
    """CRC-8 poly 0x07, MSB-first, init 0 (matches CRC8Util.calculateCRC8)."""
    crc = 0
    for b in data:
        crc = (crc ^ b) & 0xFF
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc & 0xFF


def str_to_str_hex(s: str) -> str:
    """ASCII string -> hex of each char's code (matches Conversion.strToStrHex).
    Printable ASCII (>=0x10) always yields 2 hex digits."""
    return "".join(format(ord(c), "x") for c in s)


def right_pad(hexstr: str, width: int) -> str:
    """adjustWidthBaseStr(..., true): right-pad with '0' to width."""
    return hexstr if len(hexstr) >= width else hexstr + "0" * (width - len(hexstr))


def build_confignet_cmd(ssid: str, psk: str, device_key: str,
                        bssid: str = "", open_id: str = "",
                        domain: str | None = None) -> str:
    ssid_hex = right_pad(ssid.encode("utf-8").hex(), 64) if ssid else "02" * 32
    pwd_hex = right_pad(psk.encode("utf-8").hex(), 128)
    bssid_hex = bssid.replace(":", "").replace("-", "").lower()
    if len(bssid_hex) != 12:
        bssid_hex = "000000000000"
    key_hex = right_pad(str_to_str_hex(device_key), 20)
    open_hex = right_pad(str_to_str_hex(open_id), 66)
    lat = "00000000"
    lng = "00000000"
    length = 0xA3 if domain else 0x99
    cmd = ("01" + format(length, "02x") + ssid_hex + pwd_hex + bssid_hex
           + key_hex + open_hex + lat + lng)
    if domain:
        cmd += right_pad(str_to_str_hex(domain), 20)
    return cmd


def frame_packets(cmd_hex: str, version: str = "01", data_len: int = 34) -> list[bytes]:
    """BlePackage.reqCmdToPkg: 17-byte chunks, last pkgSn |= 0x80, crc8 over 19 bytes."""
    pkts: list[bytes] = []
    n = (len(cmd_hex) + data_len - 1) // data_len
    for idx in range(n):
        chunk = right_pad(cmd_hex[idx * data_len: idx * data_len + data_len], data_len)
        sn = (idx | 0x80) if idx == n - 1 else idx
        sn_hex = format(sn, "02x")
        body = bytes.fromhex(version + sn_hex + chunk)   # 19 bytes
        pkt = body + bytes([crc8(body)])                 # 20 bytes
        pkts.append(pkt)
    return pkts


async def provision(mac: str, ssid: str, psk: str, key: str,
                    bssid: str, open_id: str, domain: str | None) -> bool:
    # App flow: (1) bind config-net with empty creds (establishes token+key),
    # then (2) creds config-net with the real ssid/psk/bssid, same openId.
    bind_cmd = build_confignet_cmd("", "", key, "", open_id, domain)
    creds_cmd = build_confignet_cmd(ssid, psk, key, bssid, open_id, domain)
    bind_pkts = frame_packets(bind_cmd)
    pkts = frame_packets(creds_cmd)
    print(f"\n  bind  cmd ({len(bind_cmd)//2} B): {bind_cmd}")
    print(f"  creds cmd ({len(creds_cmd)//2} B): {creds_cmd}")
    print(f"  creds framed into {len(pkts)} BLE packets:")
    for i, p in enumerate(pkts):
        print(f"    [{i:2d}] {p.hex()}")

    print(f"\n  scanning for {mac} ...")
    dev = await BleakScanner.find_device_by_address(mac, timeout=15.0)
    if not dev:
        print(f"  ERROR: device {mac} not found")
        return False
    print(f"  found: {dev.name}")

    notifs: list[bytes] = []
    status = {"joined": False, "cmd12": None, "cmd11": False}
    t0 = time.monotonic()
    # Reassembled-data cmd is the first data byte (pkt[2]); cmd 11/12 = config-net status.
    KEEPALIVE = bytes.fromhex("0180030254010000000000000000000000000076")

    def on_notify(_h, data: bytearray):
        pkt = bytes(data)
        notifs.append(pkt)
        tag = ""
        if len(pkt) >= 5:
            cmd = pkt[2]            # first data byte = command id
            if cmd == 0x0c:        # cmd 12 = config-net status; status byte at data[2]=pkt[4]
                st = pkt[4]
                status["cmd12"] = st
                tag = f"  <<< CMD12 config-net status=0x{st:02x}"
                if st in (0x00, 0x01):
                    status["joined"] = True
            elif cmd == 0x0b:      # cmd 11 = config-net status/progress
                status["cmd11"] = True
                tag = f"  <<< CMD11 config-net status data={pkt.hex()[4:]}"
            elif cmd == 0x01:
                tag = "  (telemetry/cmd1)"
        print(f"  << t={time.monotonic()-t0:4.1f}s {pkt.hex()}{tag}")

    try:
        async with BleakClient(dev, timeout=20.0) as client:
            print("  connected")
            await client.start_notify(NOTIFY_CHAR, on_notify)
            await asyncio.sleep(2.0)
            print("\n  >> step 1: bind config-net (creds-less) ...")
            for p in bind_pkts:
                await client.write_gatt_char(WRITE_CHAR, p, response=False)
                await asyncio.sleep(0.08)
            await asyncio.sleep(1.0)
            print("  >> step 2: creds config-net (real ssid/psk/bssid) ...")
            for p in pkts:
                await client.write_gatt_char(WRITE_CHAR, p, response=False)
                await asyncio.sleep(0.08)
            print("\n  >> holding link 60s (keepalive 10s) watching for CMD11/12 join status ...")
            for i in range(120):       # 60s
                await asyncio.sleep(0.5)
                if i % 20 == 0:        # ~every 10s
                    try:
                        await client.write_gatt_char(WRITE_CHAR, KEEPALIVE, response=False)
                    except Exception:
                        pass
                if status["joined"]:
                    print("  >>> device reports config-net SUCCESS")
                    break
            try:
                await client.stop_notify(NOTIFY_CHAR)
            except Exception:
                pass
    except Exception as e:
        print(f"  CONNECTION ERROR: {e}")
        return False

    print(f"\n  received {len(notifs)} notification(s)")
    print(f"  config-net status: cmd11_seen={status['cmd11']} cmd12_status={status['cmd12']} joined={status['joined']}")
    if status["cmd12"] is None and not status["cmd11"]:
        print("  NOTE: device never sent a CMD11/12 join status -> it did not attempt to join.")
        print("        Most likely needs the real --bssid, or a pre-step. ")
    print("  >>> Check router DHCP leases for a new device (WiFi MAC differs from BLE MAC).")
    return status["joined"]


def main():
    ap = argparse.ArgumentParser(description="Provision WiFi over BLE (real DoHome config-net format)")
    ap.add_argument("mac", help="device BLE MAC (e.g. 8C:D0:B2:A9:8C:59)")
    ap.add_argument("--ssid", required=True, help="2.4GHz WiFi SSID (max 32 bytes)")
    ap.add_argument("--psk", required=True, help="WiFi password (max 64 bytes)")
    ap.add_argument("--key", required=True, help="10-char device key (e.g. 39e0219ad0)")
    ap.add_argument("--bssid", default="", help="AP BSSID (recommended; aa:bb:cc:dd:ee:ff)")
    ap.add_argument("--openid", default=None, help="binding token (default: random 30-char, like the app)")
    ap.add_argument("--domain", default=None, help="cloud domain (default none)")
    args = ap.parse_args()
    if len(args.ssid.encode()) > 32:
        sys.exit("ssid too long (>32 bytes)")
    if len(args.psk.encode()) > 64:
        sys.exit("psk too long (>64 bytes)")
    open_id = args.openid
    if open_id is None:
        import random, string
        open_id = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(30))
        print(f"  (generated openId token: {open_id})")
    ok = asyncio.run(provision(args.mac, args.ssid, args.psk, args.key,
                               args.bssid, open_id, args.domain))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

