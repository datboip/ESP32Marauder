# ESP32 Marauder — datboip edition

Personal fork of [justcallmekoko/ESP32Marauder](https://github.com/justcallmekoko/ESP32Marauder) with QoL mods for wardriving and daily use.

## Primary Hardware Target

**ESP32 Marauder v6.1** — the official JCMK board (LOLIN D32 base + TFT touchscreen)
- Config define: `MARAUDER_V6_1` (line 17 in `configs.h`, currently active)
- TFT setup: `User_Setup_og_marauder.h`
- FQBN: `esp32:esp32:d32:PartitionScheme=min_spiffs`
- ESP-IDF version: 3.3.4
- NimBLE version: master
- Features: touch, battery, BT, NeoPixel LED, full screen, SD, GPS

## Build & Flash

```bash
# Compile for Marauder v6.1 (active define in configs.h, no build-property override needed)
arduino-cli compile --fqbn esp32:esp32:d32:PartitionScheme=min_spiffs esp32_marauder/

# Flash (adjust port as needed)
arduino-cli upload --fqbn esp32:esp32:d32 --port /dev/ttyUSB0 esp32_marauder/
```

Pre-built bins go in `build/`. The CI workflow (`.github/workflows/nightly_build.yml`) builds all board variants.

## Upstream Sync

Origin points to the datboip fork. To pull upstream changes:

```bash
# Add upstream remote (one-time)
git remote add upstream https://github.com/justcallmekoko/ESP32Marauder.git

# Fetch and merge
git fetch upstream
git merge upstream/master
```

## Project Structure

```
esp32_marauder/
├── esp32_marauder.ino    # Entry point, main loop, global object instances
├── WiFiScan.cpp/.h       # Core WiFi/BT scanning engine (largest file, ~400KB)
├── MenuFunctions.cpp/.h  # Menu UI, display rendering, touch zones
├── CommandLine.cpp/.h    # Serial CLI parser and command execution
├── Display.cpp/.h        # TFT display driver, touch input, button handling
├── AutoCycle.cpp/.h      # [datboip] Auto-cycling through scan modes
├── Buffer.cpp/.h         # Packet buffering, PCAP file I/O, SD card writes
├── configs.h             # Board selection, pin defs, feature flags (~74KB)
├── settings.cpp/.h       # NVS flash storage (Preferences API)
├── EvilPortal.cpp/.h     # Captive portal attack logic
├── GpsInterface.cpp/.h   # GPS serial driver, wardriving
├── Assets.h              # Embedded icon/splash image data
├── SDInterface.cpp/.h    # SD card operations
├── BatteryInterface.cpp/.h
├── LedInterface.cpp/.h   # NeoPixel LED control
├── Keyboard.cpp/.h       # HID keyboard emulation
├── TouchKeyboard.cpp/.h  # On-screen touch keyboard
└── libraries/            # Local lib dependencies (ESPAsyncWebServer)
```

## Architecture

- **Arduino/C++ mixed** — uses Arduino APIs for hardware, C++ classes for components
- **Global objects** instantiated in `esp32_marauder.ino` (e.g., `WiFiScan wifi_scan_obj`, `AutoCycle auto_cycle_obj`)
- **Hardware gating** via `#define` / `#ifdef` blocks in `configs.h` — features like `HAS_SCREEN`, `HAS_CYD_TOUCH`, `HAS_SD`, `HAS_GPS`, `HAS_BT`
- **Main loop** in `.ino` calls each subsystem's update method every tick
- **Serial CLI** at 115200 baud — all features accessible via `CommandLine`
- **TFT_eSPI** for display, **NimBLE** for Bluetooth, **ESPAsyncWebServer** for Evil Portal

## datboip Edition Features

These are custom additions on `feature/autocycle`:

### AutoCycle (`AutoCycle.cpp/.h`)
Automatically cycles through scan modes: Probe → Beacon → AP → Deauth Detect → BLE Scan. Configurable durations and pause between cycles. CLI: `autocycle -s start/stop/status`, `autocycle -t <idx> <secs>`, `autocycle -p <secs>`.

### Boot Shortcuts
4 corner tap zones on the splash screen (4s timeout):
- Top-Left: Wardrive
- Top-Right: AutoCycle
- Bottom-Left: Station Wardrive
- Bottom-Right: BLE Scan

### PWM Brightness
4-level backlight control (25/50/75/100%), persisted to NVS flash. Hold top/bottom touch zone 1.5s to enter brightness mode. CLI: `brightness -c` / `brightness -s 0-3`.

### Big Touch Zones
25% top / 50% select / 25% bottom layout for easier input while driving.

### CLI Additions
- `listfiles [dir]` — list files on SD card
- `readfile <path>` — read file contents from SD

## Code Conventions

- Log output uses prefixes: `[AutoCycle]`, `[WiFiScan]`, etc.
- New scan modes get a `WIFI_SCAN_*` constant and integration in `WiFiScan`, `CommandLine`, and `MenuFunctions`
- Display colors defined as TFT_eSPI constants (e.g., `TFT_CYAN`, `TFT_MAGENTA`)
- Null-check SD/buffer pointers before file operations (crash-prone area)
- Touch coordinates differ per board — always gate with `#ifdef MARAUDER_CYD_3_5_INCH` etc.

## User Preferences

- Casual communication style
- Wardriving is the primary use case
- Related project: `~/Projects/wardrive/` (wardrive data analysis, offline map viewer)
