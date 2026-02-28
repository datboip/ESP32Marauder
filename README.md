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

<h2>datboip edition</h2>

<p>
  <img src="https://img.shields.io/badge/board-Marauder_V6.1-blueviolet?style=for-the-badge" alt="Board"/>
  <img src="https://img.shields.io/badge/base-v0.13.6-blue?style=for-the-badge" alt="Version"/>
  <img src="https://img.shields.io/badge/focus-wardriving-green?style=for-the-badge" alt="Focus"/>
</p>

Custom fork with quality-of-life mods for wardriving and daily use on the V6.1 (LOLIN D32 + ILI9341 touchscreen). Built on top of [JustCallMeKoko's](https://github.com/justcallmekoko/ESP32Marauder) original firmware.

### Downloads

<table>
  <tr>
    <td>
      <a href="https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.6-datboip">
        <img src="https://img.shields.io/badge/datboip_edition-Full_Mod_Package-ff6600?style=for-the-badge&logo=github" alt="datboip edition"/>
      </a>
    </td>
    <td>All features below — AutoCycle, boot shortcuts, brightness, big touch zones, CLI extras</td>
    <td>
      <a href="https://github.com/datboip/ESP32Marauder/releases/download/v0.13.6-datboip/esp32_marauder.ino.bin">
        <img src="https://img.shields.io/badge/download-.bin-brightgreen?style=flat-square" alt="Download"/>
      </a>
    </td>
  </tr>
  <tr>
    <td>
      <a href="https://github.com/datboip/ESP32Marauder/releases/tag/v0.13.6-brightness">
        <img src="https://img.shields.io/badge/brightness_only-Clean_Patch-0099ff?style=for-the-badge&logo=github" alt="Brightness only"/>
      </a>
    </td>
    <td>PWM brightness on stock firmware — submitted as <a href="https://github.com/justcallmekoko/ESP32Marauder/pull/1142">PR #1142</a> to upstream</td>
    <td>
      <a href="https://github.com/datboip/ESP32Marauder/releases/download/v0.13.6-brightness/esp32_marauder.ino.bin">
        <img src="https://img.shields.io/badge/download-.bin-brightgreen?style=flat-square" alt="Download"/>
      </a>
    </td>
  </tr>
</table>

### How to Flash

<details>
<summary><b>Option 1 — SD Card</b> (no computer needed)</summary>
<br>
<ol>
  <li>Download <code>esp32_marauder.ino.bin</code> from the release links above</li>
  <li>Rename it to <code>update.bin</code></li>
  <li>Copy to the <b>root</b> of your SD card</li>
  <li>Insert SD into Marauder, power on</li>
  <li>Go to <b>Device → Update Firmware</b> and select the file</li>
  <li>It flashes and reboots automatically</li>
</ol>
</details>

<details>
<summary><b>Option 2 — USB</b></summary>
<br>

```bash
esptool.py --port /dev/ttyUSB0 --baud 921600 write_flash 0x10000 esp32_marauder.ino.bin
```
</details>

<details>
<summary><b>Option 3 — Build from Source</b></summary>
<br>

```bash
# Uncomment MARAUDER_V6_1 in configs.h (line 17), then:
arduino-cli compile --fqbn esp32:esp32:d32:PartitionScheme=min_spiffs esp32_marauder/

# Flash
arduino-cli upload --fqbn esp32:esp32:d32 --port /dev/ttyUSB0 esp32_marauder/
```
</details>

---

### Features

<table>
  <tr>
    <td width="80" align="center">
      <img src="https://img.shields.io/badge/-%E2%9F%B3-black?style=for-the-badge" alt="icon"/>
      <br><b>AutoCycle</b>
    </td>
    <td>
      Automatically cycles through scan modes: <b>Probe → Beacon → AP → Deauth Detect → BLE</b><br>
      Fullscreen live display with current mode, progress bar, timer, step/cycle counters<br>
      Start from main menu, tap anywhere to stop<br>
      <code>autocycle -s start/stop/status</code> · <code>autocycle -t &lt;idx&gt; &lt;secs&gt;</code> · <code>autocycle -p &lt;secs&gt;</code>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/-%E2%98%80%EF%B8%8F-black?style=for-the-badge" alt="icon"/>
      <br><b>Brightness</b>
    </td>
    <td>
      <b>10-level PWM dimming</b> (10% steps) instead of binary on/off<br>
      Persisted to NVS flash — survives reboots<br>
      Hold top or bottom touch zone <b>1.5s</b> on main menu, or <b>Device → Brightness</b><br>
      <code>brightness -c</code> (cycle) · <code>brightness -s &lt;0-9&gt;</code> (set level)
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/-%E2%9A%A1-black?style=for-the-badge" alt="icon"/>
      <br><b>Boot<br>Shortcuts</b>
    </td>
    <td>
      4 corner tap zones on the splash screen (4s timeout) — power on and go:<br><br>
      <table>
        <tr>
          <td align="center"><kbd>Wardrive</kbd><br><sub>top-left</sub></td>
          <td align="center"><kbd>AutoCycle</kbd><br><sub>top-right</sub></td>
        </tr>
        <tr>
          <td align="center"><kbd>STA Wardrive</kbd><br><sub>bottom-left</sub></td>
          <td align="center"><kbd>BLE Scan</kbd><br><sub>bottom-right</sub></td>
        </tr>
      </table>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/-%F0%9F%91%86-black?style=for-the-badge" alt="icon"/>
      <br><b>Big Touch<br>Zones</b>
    </td>
    <td>
      <b>25% / 50% / 25%</b> layout (Up / Select / Down) instead of equal thirds<br>
      Bigger top and bottom zones — easier to hit while driving
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/-%3E__-black?style=for-the-badge" alt="icon"/>
      <br><b>CLI Extras</b>
    </td>
    <td>
      <code>listfiles [dir]</code> — list files on SD card<br>
      <code>readfile &lt;path&gt;</code> — read file contents from SD<br>
      <code>autocycle</code> — control auto-cycling scan modes<br>
      <code>brightness</code> — adjust backlight
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/-%F0%9F%94%A7-black?style=for-the-badge" alt="icon"/>
      <br><b>V6.1 Fixes</b>
    </td>
    <td>
      Buffer crash when AutoCycle started without SD card<br>
      Headless mode triggering on every boot (GPIO0 held low by USB reset)<br>
      Backlight not working after flash (PWM init ordering)
    </td>
  </tr>
</table>

---

## Getting Started
Download the [latest release](https://github.com/justcallmekoko/ESP32Marauder/releases/latest) of the firmware.

Check out the project [wiki](https://github.com/justcallmekoko/ESP32Marauder/wiki) for a full overview of the ESP32 Marauder

# For Sale Now
You can buy the ESP32 Marauder using [this link](https://www.justcallmekokollc.com)
