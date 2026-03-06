# Sentinel — Remote Sensor Mode for ESP32 Marauder

## Summary

Drop-and-forget autonomous sensor mode. Device wardrives continuously, periodically connects to available WiFi networks, uploads scan data to a cloud API, pulls config/commands, and resumes scanning. mTLS authentication, dead man's switch for security.

## Architecture

Three components: firmware module, API server, web configurator.

### Firmware: Sentinel Module

New files: `Sentinel.cpp`, `Sentinel.h`

State machine:
```
IDLE -> SCANNING -> PHONE_HOME_DUE -> CONNECTING -> UPLOADING -> SYNCING -> DISCONNECTING -> SCANNING
                                                                                |
                                                              DEADMAN_WIPE <----+ (no contact for X hours)
```

Components:
- **Network matcher**: reads `networks.txt` from SD (priority,ssid,password), matches against APs discovered during wardrive, connects to best available
- **Phone-home timer**: millis()-based, configurable interval (default 30 min)
- **Chunked uploader**: reads wardrive .log files from SD in 2KB chunks, HTTP POST with Transfer-Encoding: chunked
- **Config sync**: GET /api/config, receives scan_mode, phone_home_interval, dead_man_timeout, active flag
- **Command executor**: GET /api/commands, one-shot actions (reboot, clear_sd, switch_mode, wipe)
- **Dead man's switch**: tracks last_successful_contact in NVS, wipes SD + certs + networks if exceeded
- **mTLS**: client cert + key in NVS, server validates device identity

Device identity:
- `device_id`: WiFi MAC address (automatic)
- `device_name`: user-configurable friendly name (SPIFFS settings)

CLI commands:
```
sentinel -s start/stop/status
sentinel -i <minutes>          phone-home interval
sentinel -d <hours>            dead man's timeout
sentinel -n <name>             device name
sentinel -w                    force phone-home now
sentinel -k                    wipe all sentinel data
```

SD file `networks.txt`:
```
1,MyHotspot,password123
2,STARBUCKS,
3,xfinitywifi,
```

### API Server

Flask + SQLite, deployed to Fly.io or Railway.

Endpoints:
- `POST /api/heartbeat` — device check-in (MAC, name, battery, heap, scan mode, GPS, uptime)
- `POST /api/upload` — chunked file upload (X-Filename, X-Device-Id headers)
- `GET /api/config/{device_id}` — desired config for device
- `GET /api/commands/{device_id}` — pending commands, marks dispatched
- `POST /api/ack` — command execution results

Config object:
```json
{
  "scan_mode": "wardrive",
  "phone_home_interval_min": 30,
  "dead_man_timeout_hrs": 48,
  "active": true
}
```

Command examples:
```json
[
  {"id": 1, "cmd": "reboot"},
  {"id": 2, "cmd": "switch_mode", "args": {"mode": "probe"}},
  {"id": 3, "cmd": "clear_sd"}
]
```

### Web Flasher/Configurator

Single HTML file, GitHub Pages or served by API.

Tabs:
1. **Flash** — ESPTool.js, pick .bin, flash via Web Serial
2. **Configure** — WiFi networks, sentinel settings, device name (CLI over Web Serial)
3. **Certs** — generate/upload client cert+key, push to NVS via serial
4. **Console** — live serial monitor

## Security

- mTLS: device cert validates identity, prevents impersonation
- Dead man's switch: configurable timeout (default 48h), wipes SD + certs + network list
- networks.txt on SD (not in firmware) so credentials aren't in the binary
- API key as fallback if mTLS not configured yet

## Binary Size Budget

Current: 1,775,727 / 1,966,080 bytes (90.3%), ~190KB available.

| Addition | Est. Size |
|----------|-----------|
| Sentinel class + state machine | ~8KB |
| mTLS cert handling | ~3KB |
| Network list parser | ~2KB |
| CLI commands | ~2KB |
| **Total** | **~15KB** |

## Dependencies

- ESP32 HTTPClient (in SDK, linked on use)
- WiFiClientSecure (in SDK, for mTLS)
- ArduinoJson (already used)
- No new external libraries needed

## Integration Points

- Main loop: `sentinel_obj.main(currentTime)` alongside `auto_cycle_obj.main(currentTime)`
- WiFiScan: reuses `joinWiFi()` for connections, `StartScan()` for mode switching
- Buffer: reuses existing SD write infrastructure
- Settings: adds SentinelEnabled, DeviceName, ApiUrl to SPIFFS settings
- CommandLine: adds `sentinel` command block

## Decisions

- Approach: Sentinel Split (firmware core + smart server)
- Data format: chunked raw file upload (minimal RAM)
- Control: config sync + command queue
- Auth: mTLS with dead man's switch
- Hosting: cloud free tier (Fly.io/Railway)
- Device ID: MAC + friendly name
