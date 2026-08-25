# OUPES Mega BLE — Home Assistant Integration

Custom Home Assistant integration for **OUPES Mega** power stations over
**Bluetooth (BLE)** — fully local, no cloud dependency required.

> The **WiFi** integration now lives in its own repository:
> [acalcutt/oupes-mega-wifi-hass](https://github.com/acalcutt/oupes-mega-wifi-hass).
> HACS requires one integration per repository, so the two halves of this
> project were split. The BLE and WiFi integrations can still run side by side —
> they use independent communication channels and create separate device and
> entity sets.

---

## What it does

**Direct Bluetooth connection** — the simplest setup. Connects to your OUPES
device over BLE and exposes sensors, switches, and settings entities.

- No network infrastructure needed — just a Bluetooth adapter on your HA server
  (or an ESPHome BLE proxy)
- Continuous or polled connection modes
- Supports BLE pairing (no Cleanergy app/cloud needed)
- Device control: toggle AC/DC/USB outputs, adjust settings

**[Full documentation →](custom_components/oupes_mega_ble/README.md)**

---

## Installation

### HACS (custom repository)

1. Open **HACS → Integrations**.
2. Open the three-dot menu and select **Custom repositories**.
3. Enter `https://github.com/acalcutt/oupes-mega-hass`.
4. Select **Integration**, click **Add**, and install **OUPES Mega BLE**.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/oupes_mega_ble/` into your HA config directory.
2. Restart Home Assistant.

## Quick Start

1. Power on the OUPES device and press the IoT button (indicator flashes).
2. HA auto-discovers the device — click the notification to set up.
3. Choose **Create New Key** (factory-reset the device first: hold IoT 5 s).

---

## BLE or WiFi?

| Scenario | Install |
|----------|---------|
| Simple local-only setup, device within BLE range | this integration |
| Device too far for BLE, or you want push telemetry | [oupes-mega-wifi-hass](https://github.com/acalcutt/oupes-mega-wifi-hass) |
| Want both channels for redundancy | both |

**BLE is the easiest path.** It works entirely over Bluetooth with zero network
configuration — no firewall rules, no port forwarding, no DNS tricks.

**WiFi requires network-level redirection.** The device firmware hardcodes the
cloud broker IP (`47.252.10.9`), so NAT rules are needed to intercept the
device's outbound connections and redirect them to your HA instance. More
powerful (push-based, real-time, works at any distance) but a more involved
setup.

---

## Supported Models

| Series | Models |
|--------|--------|
| **Mega** | Mega 1, Mega 2, Mega 3, Mega 5 |
| **Exodus** | Exodus 1200, Exodus 1500, Exodus 2400, S024 Lite, S1 Lite |
| **Guardian** | Guardian 6000, HP2500, D5 V2 |
| **Other** | S2 V2, DC 800, LP350, LP700, PB300, UPS 1200, UPS 1800 |

Model-specific features (settings, entity names) are applied automatically
based on the BLE product ID.

---

## Protocol Documentation

See [`debug_info/README.md`](debug_info/README.md) for the complete
reverse-engineered protocol reference, covering:

- BLE GATT profile, pairing/claiming protocol, packet format
- WiFi TCP broker protocol, streaming activation sequence
- Telemetry attribute map (shared across BLE and WiFi)
- Cloud API endpoints (HTTP REST + SiBo)
- Device firmware boot sequence

## Debug Tools

The [`debug_info/`](debug_info/) directory contains standalone tools:

| Script | Purpose |
|--------|---------|
| `pair_device.py` | BLE pairing + WiFi provisioning |
| `scan_ble.py` | Live BLE telemetry scanner |
| `parse_btsnoop.py` | Parse Android btsnoop HCI logs |
| `probe_key.py` | Test candidate device keys |
| `ble_diag.py` | BLE GATT diagnostics |
| `ble_confignet.py` | Send WiFi credentials to a paired device |
| `scan_wifi_ports.py` | Scan device for open network ports |
| `analyze_attr_csv.py` | Analyze BLE attribute debug logs |

---

## Credits

HACS packaging contributed by [@HeedfulCrayon](https://github.com/HeedfulCrayon)
(see [#9](https://github.com/acalcutt/oupes-mega-hass/issues/9)).

## License

See [LICENSE](LICENSE).
