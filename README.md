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
3. Enter `https://github.com/acalcutt/oupes-mega-ble-hass`.
4. Select **Integration**, click **Add**, and install **OUPES Mega BLE**.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/oupes_mega_ble/` into your HA config directory.
2. Restart Home Assistant.

## Quick Start

The two device families pair differently, and the difference is not cosmetic: on
the newer family the older pairing path destroys the pairing rather than creating
one. Check which you have before doing anything with the IoT button.

How to tell: the device advertises the BLE name `TT` (Mega series) or `WP`
(Guardian / D5 V2 / D5 6000 Plus). The Cleanergy app labels the second group
Guardian.

### Mega series (`TT`)

1. Power on the OUPES device and press the IoT button (indicator flashes).
2. HA auto-discovers the device — click the notification to set up.
3. Choose **Create a new device key** (factory-reset the device first: hold IoT 5 s),
   or **Enter an existing device key** if you already have one.

### Guardian / D5 V2 (`WP`)

These stations authenticate only the pairing that the Cleanergy app wrote into them.
Home Assistant does not create a pairing on this family, it reuses the one the app
left behind.

1. **Add the station in the Cleanergy app first**, over Bluetooth, with the phone
   next to the unit. A station that has never been added to the app has no pairing
   for Home Assistant to reuse, and it refuses every connection attempt.
2. **Get the account's numeric user ID.** The app does not display it anywhere, so do
   not look for a screen that shows it. One way to read it is the vendor login the app
   itself uses — the response carries it as `info.uid`:

   ```console
   $ curl -s -X POST http://api.upspowerstation.top/api/app/user/login        -H 'Content-Type: application/json'        -d '{"mail":"you@example.com","passwd":"...","lang":"en","platform":"android","systemVersion":34}'
   ```

   The endpoint is plain HTTP with no TLS, so send it only from a network you trust, and
   never paste the response into a bug report. With the number in hand, the device key is
   what the vendor's own app computes: `md5(user_id)[:10]`, lowercase hex.

   ```console
   $ python -c "import hashlib; print(hashlib.md5(b'12345').hexdigest()[:10])"
   ```

3. **Release the station from your phone** — force-stop the app or switch the phone's
   Bluetooth off. The station answers one Bluetooth client at a time, and Home
   Assistant holds the connection continuously while the entry is loaded.
4. In Home Assistant choose **Enter an existing device key** and enter the value from
   step 2.

> **Do not use "Create a new device key" on this family**, and do not hold the IoT
> button for 5 seconds to get there. That option exists for the older stations. On a
> Guardian the reset clears the pairing the app wrote, and the new key the integration
> creates is not accepted: measured twice on a Guardian 6000 V2, both attempts ended
> in `pairing_timeout`. Recovery is to re-pair the station in the Cleanergy app.

**Fetch key from Cleanergy cloud account** cannot work on this family. Measured on a
Guardian 6000 V2: the vendor's device record carries `device_key` as the literal string
`"WP"`, not a key, so the 10-hex-character check in `cloud_api._extract_key` rejects it.
Nothing is wrong with the account or the login - this family's key is not stored on the
vendor's servers, which is why step 2 derives it instead.

---

## BLE or WiFi?

| Scenario | Install |
|----------|---------|
| Mega series (`TT`) within Bluetooth range | this integration |
| Mega series too far for BLE, or you want push telemetry | [oupes-mega-wifi-hass](https://github.com/acalcutt/oupes-mega-wifi-hass) |
| Guardian / D5 V2 (`WP`) | this integration — Bluetooth is the only transport |

**BLE is the easiest path.** It works entirely over Bluetooth with zero network
configuration — no firewall rules, no port forwarding, no DNS tricks.

**WiFi redirection applies to the older models only.** Their firmware hardcodes the
cloud broker IP (`47.252.10.9`), so NAT rules are needed to intercept the device's
outbound connections and redirect them to your HA instance. More powerful (push-based,
real-time, works at any distance) but a more involved setup.

On Guardian / D5 V2 firmware there is no local network protocol to intercept, so the
WiFi integration cannot be used with these stations regardless of how it is configured.
If the station is out of Bluetooth range, the fix is a Bluetooth proxy nearer to it.

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

## License

See [LICENSE](LICENSE).
