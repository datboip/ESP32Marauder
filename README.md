# ESP32 Marauder — datboip edition

<p align="center">
  <img alt="datboip splash screen" src="pictures/datboip_splash.svg" width="300"/>
</p>

<p align="center">
  <b>Custom wardriving firmware for ESP32 Marauder V6 / V6.1</b>
  <br>
  Built on <a href="https://github.com/justcallmekoko/ESP32Marauder">JustCallMeKoko's ESP32 Marauder</a> v1.11.0
</p>

---

## Downloads

> **Flash the correct version for your board.** Check the front of your PCB — if it says V6.1 or V6.2, use the V6.1 bins. If it says V6, use the V6 bins. Flashing the wrong one will break touch/SD.

| Release | V6.1 | V6 |
|---------|------|-----|
| **[datboip edition](https://github.com/datboip/ESP32Marauder/releases/tag/v1.11.0-datboip)** (recommended) | [v6_1.bin](https://github.com/datboip/ESP32Marauder/releases/download/v1.11.0-datboip/marauder-datboip-v6_1.bin) | [v6.bin](https://github.com/datboip/ESP32Marauder/releases/download/v1.11.0-datboip/marauder-datboip-v6.bin) |
| **[Night Mode only](https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.1-datboip)** | [v6_1.bin](https://github.com/datboip/ESP32Marauder/releases/download/v0.13.1-datboip/marauder-nightmode-v6_1.bin) | [v6.bin](https://github.com/datboip/ESP32Marauder/releases/download/v0.13.1-datboip/marauder-nightmode-v6.bin) |

## How to Flash

**SD Card (easiest — no computer needed):**
1. Download the `.bin` for your board from the table above
2. Rename it to `update.bin`
3. Copy to the root of your SD card
4. On the Marauder: **Device > Update Firmware** > select the file
5. It flashes and reboots automatically

**USB:**
```bash
esptool.py --port /dev/ttyUSB0 --baud 921600 write_flash 0x10000 marauder-datboip-v6_1.bin
```

---

## Features

### Boot Shortcuts
4 corner tap zones on the splash screen. Tap during the 4-second boot window to jump straight into:
- **Wardrive** (top-left)
- **AutoCycle** (top-right)
- **Station Scan** (bottom-left)
- **BLE Scan** (bottom-right)

### AutoCycle
Automatically cycles through scan modes with configurable durations:

Probe Sniff (60s) → Beacon Sniff (45s) → AP Scan (30s) → Deauth Detect (30s) → BLE Scan (45s)

Fullscreen live display with current mode, progress bar, timer, and cycle counter. Also available via CLI: `autocycle -s start/stop/status`

### Night Mode / Brightness
13-level PWM brightness including ultra-low levels for pitch dark environments:
- **1%, 3%, 6%** — barely visible, perfect for night wardriving
- **Enter brightness mode:** Hold top or bottom zone for 2.5s — screen progressively dims as visual feedback
- **Adjust:** Tap top half = brighter, tap bottom half = dimmer
- **Blackout:** Hold anywhere for 3s — screen darkens each second then turns off
- **Wake:** Tap to restore last saved brightness
- **Quick blackout during scans:** Hold top zone 3s
- Auto-saves after 4s idle. Persisted to NVS flash across reboots.
- CLI: `brightness -c` / `brightness -s 0-12`
- Upstream PR: [#1165](https://github.com/justcallmekoko/ESP32Marauder/pull/1165)

### Big Touch Zones
50/50 top/bottom split for easier navigation while driving. No more accidentally hitting the wrong button.

### Live POI Tagging
Tap the bottom bar during wardrive to drop a GPS waypoint. Auto-numbered (POI 1, POI 2, etc.) and saved as GPX. Also via CLI: `wardrivepoi [label]`. *(Merged upstream)*

### Extra CLI Commands
`autocycle` · `listfiles [dir]` · `readfile <path>` · `brightness` · `wardrivepoi`

---

## Build from Source

```bash
# Uncomment your board in configs.h (line 16 for V6, line 17 for V6.1), then:
arduino-cli compile --fqbn esp32:esp32:d32 \
  --build-property "build.partitions=min_spiffs" \
  --build-property "upload.maximum_size=1966080" \
  esp32_marauder/

arduino-cli upload --fqbn esp32:esp32:d32 --port /dev/ttyUSB0 esp32_marauder/
```

---

## Credits

- [JustCallMeKoko](https://github.com/justcallmekoko) — ESP32 Marauder creator
- [ESP32 Marauder Wiki](https://github.com/justcallmekoko/ESP32Marauder/wiki) — full documentation
- [Buy a Marauder](https://www.justcallmekokollc.com) — support the original project
