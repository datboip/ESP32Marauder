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

### What's Different

**Cyberpunk Boot Splash**
- Animated boot sequence with border draw-in, typewriter title, magenta underline, circuit trace details, and accent lines
- Credits JustCallMeKoko as original author

**AutoCycle Mode**
- Cycles through scan modes automatically: Probe Sniff, Beacon Sniff, AP Scan, Deauth Detect, BLE Scan
- Fullscreen live status display with current mode, progress bar, timer, step/cycle counters
- Start from main menu, tap anywhere to stop
- Also available via CLI: `autocycle -s start/stop/status`
- Configurable per-mode durations and pause time via CLI

**PWM Brightness Control**
- 4-level PWM dimming (25%, 50%, 75%, 100%) instead of binary on/off
- Saved to flash, persists across reboots
- Hold top or bottom touch zone for 1.5s to enter brightness mode
- Also in Device > Brightness menu and CLI: `brightness -c` / `brightness -s 0-3`

**Big Touch Zones**
- 25% / 50% / 25% layout (Up / Select / Down) instead of equal thirds
- Larger top and bottom zones for easier navigation

**Bug Fixes**
- Fixed Buffer crash (null `fs` pointer in `setPathPrefix`)
- Fixed headless mode false trigger on V6/V6.1 (GPIO0 held low by USB reset)
- Fixed backlight init order (PWM after display init)

### Building

```bash
arduino-cli compile \
  --fqbn esp32:esp32:d32:PartitionScheme=min_spiffs \
  --build-property "build.defines=-DMARAUDER_V6_1" \
  esp32_marauder
```

### Flashing

```bash
esptool --port /dev/ttyUSB1 --baud 921600 erase_flash
esptool --port /dev/ttyUSB1 --baud 921600 write-flash 0x0 build/esp32_marauder.ino.merged.bin
```

---

## Getting Started
Download the [latest release](https://github.com/justcallmekoko/ESP32Marauder/releases/latest) of the firmware.

Check out the project [wiki](https://github.com/justcallmekoko/ESP32Marauder/wiki) for a full overview of the ESP32 Marauder

# For Sale Now
You can buy the ESP32 Marauder using [this link](https://www.justcallmekokollc.com)
