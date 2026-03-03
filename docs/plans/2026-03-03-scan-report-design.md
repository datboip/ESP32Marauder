# Marauder Scan Report Generator — Design

## Overview
Single-file Python script (`tools/marauder_report.py`) that connects to ESP32 Marauder over serial, runs a full scan suite, and generates HTML + markdown reports.

## CLI Usage
```bash
python tools/marauder_report.py --port /dev/ttyUSB0
python tools/marauder_report.py --port /dev/ttyUSB0 --output ~/reports/
python tools/marauder_report.py --port /dev/ttyUSB0 --scans wifi,bt,probe
```

## Scan Sequence

| # | Command | Default Duration | List Command | Captures |
|---|---------|-----------------|-------------|----------|
| 1 | `scanap` | 15s | `list -a` | WiFi APs (SSID, BSSID, channel, RSSI) |
| 2 | `scansta` | 20s | `list -c` | Stations per AP (MAC addresses) |
| 3 | `sniffprobe` | 30s | `list -p` | Probe requests |
| 4 | `sniffbt` | 30s | live parse | Bluetooth devices |
| 5 | `gpsdata` | 5s | live parse | GPS fix (lat/lon/alt/speed) |
| 6 | `sniffdeauth` | 20s | live parse | Deauth frames |
| 7 | `sniffpmkid` | 20s | live parse | PMKID captures |

Durations overridable via `--ap-time`, `--sta-time`, `--bt-time`, etc.

## Architecture

### Serial Communication
- 115200 baud (Marauder default)
- Send command, read lines until stopscan completes
- Regex-based parsing of known output formats
- Timeout safety: force stopscan if no data for 5s after expected duration

### Output Formats
- `report_YYYY-MM-DD_HHMMSS.html` — dark-themed styled HTML with tables
- `report_YYYY-MM-DD_HHMMSS.md` — markdown tables

### Report Sections
1. Header with timestamp and GPS coordinates (if available)
2. WiFi AP table (sorted by RSSI)
3. Station associations table
4. Probe requests list
5. Bluetooth devices table
6. Deauth/PMKID activity summary

### Error Handling
- Auto-detect serial port if --port not given
- Graceful skip if scan type not supported (no BT, no GPS)
- Ctrl+C sends stopscan before exiting

## Dependencies
- pyserial

## Approach
Single file, no templates. Inline HTML/CSS for report generation. Keeps it portable and easy to hack on.
