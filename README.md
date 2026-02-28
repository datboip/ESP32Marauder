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

Custom fork with QoL mods for wardriving and daily use on the V6.1 (LOLIN D32 + ILI9341 touchscreen). Built on [JustCallMeKoko's](https://github.com/justcallmekoko/ESP32Marauder) original firmware.

<p align="center">
  <img alt="datboip splash screen" src="https://raw.githubusercontent.com/datboip/ESP32Marauder/feature/autocycle/pictures/datboip_splash.svg" width="300"/>
</p>

### Downloads

| Release | Description | Download |
|---------|-------------|----------|
| **[datboip edition](https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.6-datboip)** | Full mod package — all features below | [.bin](https://github.com/datboip/ESP32Marauder/releases/download/v0.13.6-datboip/esp32_marauder.ino.bin) |
| **[Brightness only](https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.6-brightness)** | Clean PWM brightness patch on stock firmware ([PR #1142](https://github.com/justcallmekoko/ESP32Marauder/pull/1142)) | [.bin](https://github.com/datboip/ESP32Marauder/releases/download/v0.13.6-brightness/esp32_marauder.ino.bin) |

### How to Flash

**SD Card (easiest — no computer needed):**
1. Download the `.bin` from the table above
2. Rename it to `update.bin`
3. Copy to the root of your SD card
4. On the Marauder: **Device → Update Firmware** → select the file
5. It flashes and reboots automatically

**USB:**
```bash
esptool.py --port /dev/ttyUSB0 --baud 921600 write_flash 0x10000 esp32_marauder.ino.bin
```

**Build from source:**
```bash
# Uncomment MARAUDER_V6_1 in configs.h (line 17), then:
arduino-cli compile --fqbn esp32:esp32:d32:PartitionScheme=min_spiffs esp32_marauder/
arduino-cli upload --fqbn esp32:esp32:d32 --port /dev/ttyUSB0 esp32_marauder/
```

### Features

**AutoCycle** — Automatically cycles through scan modes: Probe → Beacon → AP → Deauth Detect → BLE. Fullscreen live display with progress bar, timer, step/cycle counters. Start from menu or CLI: `autocycle -s start/stop/status`

**PWM Brightness** — 10-level dimming (10% steps) instead of binary on/off. Persisted to NVS flash. Hold top or bottom touch zone 1.5s on main menu, or Device → Brightness. CLI: `brightness -c` / `brightness -s <0-9>`

**Boot Shortcuts** — 4 corner tap zones on the splash screen (shown in image above). Tap during the 4s boot window to jump straight into Wardrive, AutoCycle, Station Wardrive, or BLE Scan.

**Big Touch Zones** — 25% / 50% / 25% layout (Up / Select / Down) instead of equal thirds. Easier to hit while driving.

**Extra CLI** — `listfiles [dir]` · `readfile <path>` · `autocycle` · `brightness`

**V6.1 Fixes** — Buffer crash without SD card, headless mode on every boot, backlight init ordering.

---

## Getting Started
Download the [latest release](https://github.com/justcallmekoko/ESP32Marauder/releases/latest) of the firmware.

Check out the project [wiki](https://github.com/justcallmekoko/ESP32Marauder/wiki) for a full overview of the ESP32 Marauder

# For Sale Now
You can buy the ESP32 Marauder using [this link](https://www.justcallmekokollc.com)
