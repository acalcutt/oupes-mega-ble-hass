# OUPES Mega BLE brand assets

- `icon.png` — the square integration icon.
- `logo.png` — wider artwork for surfaces that support a logo.

HACS reads brand assets from this path (`custom_components/<domain>/brand/`)
and its validation falls back to the
[home-assistant/brands](https://github.com/home-assistant/brands) repository
when they are absent, so these files must stay inside the integration folder.
