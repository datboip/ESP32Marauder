# Sentinel — Remote Sensor Mode

Drop-and-forget autonomous scan mode for ESP32 Marauder. Wardrives continuously, phones home over WiFi to upload data and pull commands.

## Quick Start

### 1. Flash firmware

Use the web configurator at `tools/web/sentinel.html` (open in Chrome), or flash via CLI:

```bash
arduino-cli compile --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" esp32_marauder/esp32_marauder.ino
arduino-cli upload --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" --port /dev/ttyUSB0 esp32_marauder/esp32_marauder.ino
```

### 2. Create networks.txt on SD card

Create a file called `networks.txt` in the root of the SD card:

```
# priority,ssid,password (empty password = open network)
1,MyHotspot,password123
2,STARBUCKS,
3,xfinitywifi,
```

Lower priority number = tried first. The device will scan for these networks and connect to the best available one when phoning home.

### 3. Deploy the API server

```bash
cd tools
export API_KEYS="your-secret-key"
python3 sentinel_server.py
```

The server runs on port 5001 by default. For production, deploy to Fly.io, Railway, or any host that supports Python/Flask.

Environment variables:
- `PORT` — server port (default: 5001)
- `API_KEYS` — comma-separated API keys (default: "changeme")
- `DB_PATH` — SQLite database path (default: "sentinel.db")
- `UPLOAD_DIR` — directory for uploaded files (default: "uploads")

### 4. Configure the device

Over serial (115200 baud):

```
sentinel -u https://your-server.fly.dev
sentinel -a your-secret-key
sentinel -n starbucks-east
sentinel -i 30
sentinel -s start
```

Or use the web configurator's Configure tab.

## CLI Commands

```
sentinel                          Show status
sentinel -s start                 Start sentinel mode
sentinel -s stop                  Stop sentinel mode
sentinel -s status                Show detailed status
sentinel -i <minutes>             Set phone-home interval (default: 30)
sentinel -d <hours>               Set dead man's timeout (default: 48)
sentinel -n <name>                Set device friendly name
sentinel -u <url>                 Set API server URL
sentinel -a <key>                 Set API key
sentinel -w                       Force phone-home now
sentinel -k                       Wipe all sentinel config
```

## How It Works

### State Machine

```
SCANNING → PHONE_HOME_DUE → CONNECTING → UPLOADING → SYNCING → DISCONNECTING → SCANNING
                                                                      ↓
                                                          DEADMAN_WIPE (if no contact for X hours)
```

1. **SCANNING** — runs wardrive (or configured scan mode), logs to SD card as normal
2. **PHONE_HOME_DUE** — timer fires, stops scanning
3. **CONNECTING** — scans for known WiFi networks from `networks.txt`, connects to best match
4. **UPLOADING** — sends heartbeat, then uploads all `.log` and `.gpx` files to API server
5. **SYNCING** — pulls config updates and pending commands from server
6. **DISCONNECTING** — disconnects WiFi, resumes scanning

### Network Matching

The device reads `networks.txt` from SD, sorted by priority. During phone-home, it does a quick WiFi scan and connects to the highest-priority network it can find. This means:

- **Your phone hotspot** (priority 1) — roll up to check on the device
- **Nearby open WiFi** (priority 2-3) — Starbucks, xfinity, etc.
- If no known network is found, it skips the phone-home and keeps scanning

### Dead Man's Switch

If the device can't reach the API server for the configured timeout (default 48 hours), it wipes:
- All scan data files (.log, .gpx, .pcap) from SD
- The networks.txt file
- API URL, API key, and device name from settings
- Then reboots

This prevents data recovery if the device is stolen or discovered.

## API Server Endpoints

All endpoints require `X-API-Key` header.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/heartbeat` | Device check-in with status |
| POST | `/api/upload` | Chunked file upload |
| GET | `/api/config/<device_id>` | Get device config |
| PUT | `/api/config/<device_id>` | Update device config |
| GET | `/api/commands/<device_id>` | Fetch pending commands |
| POST | `/api/commands/<device_id>` | Queue a command |
| POST | `/api/ack` | Acknowledge command execution |
| GET | `/api/devices` | List all devices |
| GET | `/api/uploads/<device_id>` | List uploads for device |

### Heartbeat payload

```json
{
  "device_id": "88:13:BF:2F:E4:CC",
  "device_name": "starbucks-east",
  "scan_mode": "wardrive",
  "uptime_sec": 3600,
  "free_heap": 245000,
  "state": "SCANNING",
  "battery_pct": 85,
  "lat": "33.7490",
  "lon": "-84.3880"
}
```

### Remote commands

Queue commands via the API:

```bash
# Reboot device
curl -X POST http://server:5001/api/commands/88:13:BF:2F:E4:CC \
  -H "X-API-Key: your-key" -H "Content-Type: application/json" \
  -d '{"cmd": "reboot"}'

# Switch scan mode
curl -X POST ... -d '{"cmd": "switch_mode", "args": "probe"}'

# Clear SD card data
curl -X POST ... -d '{"cmd": "clear_sd"}'

# Emergency wipe
curl -X POST ... -d '{"cmd": "wipe"}'
```

### Update device config remotely

```bash
curl -X PUT http://server:5001/api/config/88:13:BF:2F:E4:CC \
  -H "X-API-Key: your-key" -H "Content-Type: application/json" \
  -d '{"scan_mode": "probe", "phone_home_interval_min": 15}'
```

The device pulls this config on its next phone-home cycle.

## Web Configurator

Open `tools/web/sentinel.html` in Chrome or Edge (requires Web Serial API).

**Tabs:**
- **Flash** — select .bin file and flash via ESPTool.js
- **Configure** — set WiFi networks, sentinel settings, device name
- **Certs** — mTLS certificate upload (coming soon)
- **Console** — live serial monitor with command input

## File Structure

```
esp32_marauder/
  Sentinel.h          # State machine, structs, class definition
  Sentinel.cpp        # Core implementation
  CommandLine.cpp     # sentinel CLI command handler
  settings.cpp        # DeviceName, ApiUrl, ApiKey settings

tools/
  sentinel_server.py  # Flask API server
  sentinel_schema.sql # SQLite schema
  web/
    sentinel.html     # Web flasher + configurator

SD card:
  networks.txt        # WiFi network list (priority,ssid,password)
  *.log               # Wardrive scan data (Wigle CSV format)
  *.gpx               # POI waypoint files
  *.uploaded           # Files already uploaded to server
```

## Security Notes

- API key required for all server endpoints
- Dead man's switch wipes data if device goes dark
- `networks.txt` lives on SD card, not in firmware binary
- mTLS support planned (cert tab in web configurator is placeholder)
- Uploaded files are stored per-device with timestamps, never overwritten
