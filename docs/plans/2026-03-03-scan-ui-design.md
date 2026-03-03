# Marauder Scan UI — Design

## Overview
Flask web dashboard (`tools/marauder_ui.py`) for controlling ESP32 Marauder scans and browsing reports. Runs locally, accessible from browser or phone on same network.

## Architecture
- Single-file Flask app, imports parsing logic from `marauder_report.py`
- All HTML/CSS/JS inline (same single-file philosophy)
- Serial connection as app-level global
- Background thread for scans, SSE for live streaming to browser
- Reports saved to configurable directory

```
Browser <--SSE--> Flask <--serial--> ESP32 Marauder
                    |
                    +--> reports/*.html, reports/*.md
```

## UI Layout

### Dashboard (`/`)
- **Connection panel:** serial port selector, connect/disconnect, status LED
- **Scan cards:** grid of cards per scan type (WiFi AP, Station, Probe, BT, GPS, Deauth, PMKID), each with start/stop button, duration slider, live item count badge
- **"Run All" button:** sequential full scan suite
- **Live feed:** scrolling serial output log
- **"Generate Report" button:** create HTML+MD from current data

### Reports (`/reports`)
- List of past reports with timestamps
- Click to view inline
- Delete button per report

## API Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Dashboard page |
| GET | `/reports` | Reports browser |
| GET | `/reports/<filename>` | View specific report |
| POST | `/api/connect` | Connect to serial port |
| POST | `/api/disconnect` | Disconnect serial |
| POST | `/api/scan/start` | Start scan `{type, duration}` |
| POST | `/api/scan/stop` | Stop current scan |
| POST | `/api/scan/all` | Run full scan suite |
| POST | `/api/report/generate` | Generate report from current data |
| DELETE | `/api/report/<filename>` | Delete report |
| GET | `/api/stream` | SSE live scan data |
| GET | `/api/status` | Connection + scan status |

## Dependencies
- flask
- pyserial (already have)

## Style
- Dark theme matching existing HTML reports (#0a0a0a bg, #00ff41 green, #ffaa00 amber)
- Monospace font, hacker aesthetic
- Responsive for phone access

## CLI Usage
```bash
python tools/marauder_ui.py                          # localhost:5000
python tools/marauder_ui.py --host 0.0.0.0           # accessible from phone
python tools/marauder_ui.py --port 8080              # custom port
python tools/marauder_ui.py --reports-dir ~/reports   # custom report dir
```

## v2 (Future)
- Ollama integration for AI-powered scan analysis
- Settings page for default durations, baud rate
