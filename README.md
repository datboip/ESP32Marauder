<!---[![License: MIT](https://img.shields.io/github/license/mashape/apistatus.svg)](https://github.com/justcallmekoko/ESP32Marauder/blob/master/LICENSE)--->
<!---[![Gitter](https://badges.gitter.im/justcallmekoko/ESP32Marauder.png)](https://gitter.im/justcallmekoko/ESP32Marauder)--->
<!---[![Build Status](https://travis-ci.com/justcallmekoko/ESP32Marauder.svg?branch=master)](https://travis-ci.com/justcallmekoko/ESP32Marauder)--->
<!---Shields/Badges https://shields.io/--->

# ESP32 Marauder
<p align="center"><img alt="Marauder logo" src="https://github.com/justcallmekoko/ESP32Marauder/blob/master/pictures/marauder_skull_patch_04_full_final.png?raw=true" width="300"></p>
<p align="center">
  <b>A suite of WiFi/Bluetooth offensive and defensive tools for the ESP32</b>
  <br><br>
  <a href="https://github.com/justcallmekoko/ESP32Marauder/blob/master/LICENSE"><img alt="License" src="https://img.shields.io/github/license/mashape/apistatus.svg"></a>
  <a href="https://gitter.im/justcallmekoko/ESP32Marauder"><img alt="Gitter" src="https://badges.gitter.im/justcallmekoko/ESP32Marauder.png"/></a>
  <a href="https://github.com/justcallmekoko/ESP32Marauder/releases/latest"><img src="https://img.shields.io/github/downloads/justcallmekoko/ESP32Marauder/total" alt="Downloads"/></a>
  <br>
  <a href="https://twitter.com/intent/follow?screen_name=jcmkyoutube"><img src="https://img.shields.io/twitter/follow/jcmkyoutube?style=social&logo=twitter" alt="Twitter"></a>
  <a href="https://www.instagram.com/just.call.me.koko"><img src="https://img.shields.io/badge/Follow%20Me-Instagram-orange" alt="Instagram"/></a>
  <br><br>
</p>
    
[![Build and Push](https://github.com/justcallmekoko/ESP32Marauder/actions/workflows/build_push.yml/badge.svg)](https://github.com/justcallmekoko/ESP32Marauder/actions/workflows/build_push.yml)

---

## datboip edition

Custom fork of ESP32 Marauder for the V6.1 (LOLIN D32 + ILI9341 touchscreen) with quality-of-life mods for wardriving and daily use. Built on top of [JustCallMeKoko's](https://github.com/justcallmekoko/ESP32Marauder) original firmware.

### Downloads

Two pre-compiled releases available for Marauder V6.1:

| Release | Description | Download |
|---------|-------------|----------|
| **[datboip edition](https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.6-datboip)** | Full mod package — all features below | [esp32_marauder.ino.bin](https://github.com/datboip/ESP32Marauder/releases/download/v0.13.6-datboip/esp32_marauder.ino.bin) |
| **[Brightness only](https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.6-brightness)** | Clean PWM brightness add-on for stock firmware | [esp32_marauder.ino.bin](https://github.com/datboip/ESP32Marauder/releases/download/v0.13.6-brightness/esp32_marauder.ino.bin) |

> The **brightness-only** release is a minimal patch on top of upstream — no other changes. It's also submitted as [PR #1142](https://github.com/justcallmekoko/ESP32Marauder/pull/1142) to upstream.

### What's in the datboip edition

```
╔═══════════════════════════════════════════════╗
║        ESP32 Marauder  ·  datboip edition     ║
║                    v0.13.6                    ║
╠═══════════════════════════════════════════════╣
║                                               ║
║   BOOT SHORTCUTS (tap during 4s splash)       ║
║                                               ║
║   ┌──────────────┐   ┌──────────────────┐     ║
║   │   WARDRIVE   │   │    AUTOCYCLE     │     ║
║   │     (TL)     │   │      (TR)        │     ║
║   └──────────────┘   └──────────────────┘     ║
║   ┌──────────────┐   ┌──────────────────┐     ║
║   │  STA WDRIVE  │   │    BLE SCAN     │     ║
║   │     (BL)     │   │      (BR)        │     ║
║   └──────────────┘   └──────────────────┘     ║
║                                               ║
╠═══════════════════════════════════════════════╣
║                                               ║
║   TOUCH LAYOUT          BRIGHTNESS            ║
║   ┌─────────────┐                             ║
║   │  ▲ UP  25%  │       Hold any zone 1.5s    ║
║   ├─────────────┤       to enter adjust mode  ║
║   │             │                             ║
║   │ ■ SEL  50% │       ░░░░░░░░░█████ 100%   ║
║   │             │       10 levels · NVS saved ║
║   ├─────────────┤                             ║
║   │  ▼ DN  25%  │                             ║
║   └─────────────┘                             ║
║                                               ║
╚═══════════════════════════════════════════════╝
```

**AutoCycle Mode**
- Automatically cycles through scan modes: Probe → Beacon → AP → Deauth Detect → BLE
- Fullscreen live display with current mode, progress bar, timer, step/cycle counters
- Start from main menu or CLI: `autocycle -s start/stop/status`
- Configurable per-mode durations and pause time

**PWM Brightness Control**
- 10-level PWM dimming (10% steps) instead of binary on/off
- Persisted to NVS flash across reboots
- Hold top or bottom touch zone 1.5s on main menu, or Device → Brightness
- CLI: `brightness -c` (cycle) / `brightness -s <0-9>` (set level)

**Boot Shortcuts**
- 4 corner tap zones on the splash screen (4s timeout)
- Top-Left: Wardrive / Top-Right: AutoCycle / Bottom-Left: Station Wardrive / Bottom-Right: BLE Scan
- Power on and go — no menu navigation needed

**Big Touch Zones**
- 25% / 50% / 25% layout (Up / Select / Down) instead of equal thirds
- Easier to hit while driving

**Extra CLI Commands**
- `listfiles [dir]` — list files on SD card
- `readfile <path>` — read file contents from SD
- `autocycle` — control auto-cycling scan modes
- `brightness` — adjust backlight

**Cyberpunk Boot Splash**
- Animated boot sequence with border draw-in, typewriter title, circuit traces
- Credits JustCallMeKoko as original author

**V6.1 Fixes**
- Buffer crash when AutoCycle started without SD card
- Headless mode triggering on every boot (GPIO0 held low by USB reset)
- Backlight not working after flash (PWM init ordering)

### Flashing

**Option 1 — SD card (no computer needed)**
1. Download `esp32_marauder.ino.bin` from releases above
2. Rename it to `update.bin`
3. Copy to the root of your SD card
4. On the Marauder, go to **Device → Update Firmware** and select the file
5. It flashes and reboots automatically

**Option 2 — USB**
```bash
esptool.py --port /dev/ttyUSB0 --baud 921600 write_flash 0x10000 esp32_marauder.ino.bin
```

### Building from Source

```bash
# Uncomment MARAUDER_V6_1 in configs.h (line 17), then:
arduino-cli compile --fqbn esp32:esp32:d32:PartitionScheme=min_spiffs esp32_marauder/

# Flash
arduino-cli upload --fqbn esp32:esp32:d32 --port /dev/ttyUSB0 esp32_marauder/
```

---

## Getting Started
Download the [latest release](https://github.com/justcallmekoko/ESP32Marauder/releases/latest) of the firmware.

Check out the project [wiki](https://github.com/justcallmekoko/ESP32Marauder/wiki) for a full overview of the ESP32 Marauder

# For Sale Now
You can buy the ESP32 Marauder using [this link](https://www.justcallmekokollc.com)
