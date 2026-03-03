# Marauder Scan Report Generator — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a single-file Python script that connects to ESP32 Marauder over serial, runs all scan types, and generates HTML + markdown reports.

**Architecture:** One file (`tools/marauder_report.py`) using pyserial. Sequentially runs scans, parses known serial output formats with regex, collects data into dicts/lists, then renders to HTML (inline CSS, dark theme) and markdown. Ctrl+C handler ensures `stopscan` is always sent.

**Tech Stack:** Python 3, pyserial

---

### Task 1: Scaffold script with CLI args and serial connection

**Files:**
- Create: `tools/marauder_report.py`

**Step 1: Create the script with argparse and serial connection logic**

```python
#!/usr/bin/env python3
"""Marauder Scan Report Generator — connect to ESP32 Marauder over serial,
run a full scan suite, and generate HTML + markdown reports."""

import argparse
import glob
import os
import re
import signal
import sys
import time
from datetime import datetime

try:
    import serial
except ImportError:
    print("pyserial required: pip install pyserial")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Serial helpers
# ---------------------------------------------------------------------------

def find_serial_port():
    """Auto-detect common USB-serial ports."""
    patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*",
                "/dev/cu.SLAB*", "COM*"]
    for pat in patterns:
        ports = glob.glob(pat)
        if ports:
            return sorted(ports)[0]
    return None


def connect(port, baud=115200):
    """Open serial connection and flush any stale data."""
    ser = serial.Serial(port, baud, timeout=1)
    time.sleep(2)  # wait for ESP32 boot/reset
    ser.reset_input_buffer()
    return ser


def send_cmd(ser, cmd):
    """Send a CLI command and give Marauder a moment to start processing."""
    ser.write((cmd + "\n").encode())
    time.sleep(0.3)


def read_lines(ser, duration, stop_early=None):
    """Read serial lines for *duration* seconds.
    Returns list of decoded strings.
    If *stop_early* regex matches a line, stop immediately."""
    lines = []
    deadline = time.time() + duration
    while time.time() < deadline:
        raw = ser.readline()
        if raw:
            line = raw.decode(errors="replace").strip()
            if line:
                lines.append(line)
                if stop_early and re.search(stop_early, line):
                    break
    return lines


def stop_scan(ser):
    """Send stopscan and drain remaining output."""
    send_cmd(ser, "stopscan")
    time.sleep(1)
    ser.reset_input_buffer()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description="Marauder full-scan report generator")
    p.add_argument("--port", help="Serial port (auto-detect if omitted)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--output", default=".", help="Output directory for reports")
    p.add_argument("--scans", default="all",
                   help="Comma-separated scan list: wifi,bt,probe,deauth,pmkid,gps or 'all'")
    p.add_argument("--ap-time", type=int, default=15, help="AP scan duration (s)")
    p.add_argument("--sta-time", type=int, default=20, help="Station scan duration (s)")
    p.add_argument("--probe-time", type=int, default=30, help="Probe sniff duration (s)")
    p.add_argument("--bt-time", type=int, default=30, help="BT scan duration (s)")
    p.add_argument("--gps-time", type=int, default=5, help="GPS data read duration (s)")
    p.add_argument("--deauth-time", type=int, default=20, help="Deauth sniff duration (s)")
    p.add_argument("--pmkid-time", type=int, default=20, help="PMKID sniff duration (s)")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    port = args.port or find_serial_port()
    if not port:
        print("No serial port found. Use --port to specify.")
        sys.exit(1)

    print(f"[*] Connecting to {port} @ {args.baud} baud...")
    ser = connect(port, args.baud)

    # Ctrl+C safety: always stopscan before exit
    def sigint_handler(sig, frame):
        print("\n[!] Interrupted — sending stopscan...")
        stop_scan(ser)
        ser.close()
        sys.exit(1)
    signal.signal(signal.SIGINT, sigint_handler)

    print(f"[*] Connected. Starting scan suite...")
    # (scan logic goes here in next tasks)
    ser.close()
```

**Step 2: Verify the script runs**

Run: `python tools/marauder_report.py --help`
Expected: argparse help output showing all flags.

**Step 3: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: scaffold marauder report script with CLI and serial helpers"
```

---

### Task 2: Implement WiFi scan (AP + Station + Probe)

**Files:**
- Modify: `tools/marauder_report.py`

**Step 1: Add WiFi scan functions**

Add these functions after the serial helpers section:

```python
# ---------------------------------------------------------------------------
# Parsers — WiFi
# ---------------------------------------------------------------------------

# list -a output: [0][CH:6] MyNetwork -45
RE_AP = re.compile(r"\[(\d+)\]\[CH:(\d+)\]\s+(.+?)\s+(-?\d+)(\s+\(selected\))?$")

# list -c output: [0] MyNetwork -45:
#                   [1] aa:bb:cc:dd:ee:ff
RE_STA_HEADER = re.compile(r"^\[(\d+)\]\s+(.+?)\s+(-?\d+):$")
RE_STA_ENTRY = re.compile(r"^\s+\[(\d+)\]\s+([0-9a-fA-F:]{17})")

# list -p output: [0] SomeSSID
RE_PROBE = re.compile(r"^\[(\d+)\]\s+(.+)$")

# Live probe output: -65 Ch: 6 Client: aa:bb:cc:dd:ee:ff Requesting: SomeSSID
RE_PROBE_LIVE = re.compile(
    r"(-?\d+)\s+Ch:\s*(\d+)\s+Client:\s+([0-9a-fA-F:]{17})\s+Requesting:\s*(.*)")


def scan_aps(ser, duration):
    """Run scanap, wait, stopscan, then list -a to get results."""
    print(f"[>] Scanning APs for {duration}s...")
    send_cmd(ser, "scanap")
    # read live output (we don't parse it — list -a is more reliable)
    read_lines(ser, duration)
    stop_scan(ser)

    # Get structured list
    send_cmd(ser, "list -a")
    lines = read_lines(ser, 5)
    aps = []
    for line in lines:
        m = RE_AP.match(line)
        if m:
            aps.append({
                "index": int(m.group(1)),
                "channel": int(m.group(2)),
                "essid": m.group(3).strip(),
                "rssi": int(m.group(4)),
            })
    aps.sort(key=lambda a: a["rssi"], reverse=True)
    print(f"    Found {len(aps)} APs")
    return aps


def scan_stations(ser, duration):
    """Run scansta, wait, stopscan, then list -c to get results."""
    print(f"[>] Scanning stations for {duration}s...")
    send_cmd(ser, "scansta")
    read_lines(ser, duration)
    stop_scan(ser)

    send_cmd(ser, "list -c")
    lines = read_lines(ser, 5)
    stations = []
    current_ap = None
    for line in lines:
        m = RE_STA_HEADER.match(line)
        if m:
            current_ap = {"essid": m.group(2).strip(), "rssi": int(m.group(3)),
                          "stations": []}
            stations.append(current_ap)
            continue
        m = RE_STA_ENTRY.match(line)
        if m and current_ap is not None:
            current_ap["stations"].append(m.group(2))
    total = sum(len(a["stations"]) for a in stations)
    print(f"    Found {total} stations across {len(stations)} APs")
    return stations


def scan_probes(ser, duration):
    """Run sniffprobe, collect live output, then also list -p."""
    print(f"[>] Sniffing probes for {duration}s...")
    send_cmd(ser, "sniffprobe")
    live = read_lines(ser, duration)
    stop_scan(ser)

    # Parse live probe lines for richer data (includes MAC + channel)
    probes_live = []
    for line in live:
        m = RE_PROBE_LIVE.match(line)
        if m:
            probes_live.append({
                "rssi": int(m.group(1)),
                "channel": int(m.group(2)),
                "client_mac": m.group(3),
                "essid": m.group(4).strip(),
            })

    # Also grab the list for unique SSIDs
    send_cmd(ser, "list -p")
    list_lines = read_lines(ser, 5)
    unique_ssids = []
    for line in list_lines:
        m = RE_PROBE.match(line)
        if m:
            unique_ssids.append(m.group(2).strip())

    print(f"    Captured {len(probes_live)} probe requests ({len(unique_ssids)} unique SSIDs)")
    return {"live": probes_live, "unique_ssids": unique_ssids}
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('tools/marauder_report.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: add WiFi AP/station/probe scan + parsing"
```

---

### Task 3: Implement BT, GPS, deauth, and PMKID scans

**Files:**
- Modify: `tools/marauder_report.py`

**Step 1: Add remaining scan functions**

Add after the WiFi parsers:

```python
# ---------------------------------------------------------------------------
# Parsers — Bluetooth
# ---------------------------------------------------------------------------

# sniffbt live: -65 Device: MyDevice  or  -65 Device: aa:bb:cc:dd:ee:ff
RE_BT = re.compile(r"(-?\d+)\s+Device:\s+(.+)")
# Also handle the flipper/airtag variant: -65 MAC: aa:bb:cc:dd:ee:ff
RE_BT_MAC = re.compile(r"(-?\d+)\s+MAC:\s+([0-9a-fA-F:]{17})")


def scan_bt(ser, duration):
    """Run sniffbt, parse live output for BT devices."""
    print(f"[>] Scanning Bluetooth for {duration}s...")
    send_cmd(ser, "sniffbt")
    lines = read_lines(ser, duration)
    stop_scan(ser)

    devices = []
    seen = set()
    for line in lines:
        m = RE_BT.match(line)
        if m:
            name = m.group(2).strip()
            if name not in seen:
                seen.add(name)
                devices.append({"rssi": int(m.group(1)), "name": name})
            continue
        m = RE_BT_MAC.match(line)
        if m:
            mac = m.group(2).strip()
            if mac not in seen:
                seen.add(mac)
                devices.append({"rssi": int(m.group(1)), "name": mac})

    devices.sort(key=lambda d: d["rssi"], reverse=True)
    print(f"    Found {len(devices)} BT devices")
    return devices


# ---------------------------------------------------------------------------
# Parsers — GPS
# ---------------------------------------------------------------------------

RE_GPS_FIELD = re.compile(r"(Fix|Sats|Lat|Lon|Alt|Accuracy|Date/Time):\s*(.+)")


def read_gps(ser, duration):
    """Run gpsdata briefly, parse fix info."""
    print(f"[>] Reading GPS data for {duration}s...")
    send_cmd(ser, "gpsdata")
    lines = read_lines(ser, duration)
    stop_scan(ser)

    gps = {}
    for line in lines:
        m = RE_GPS_FIELD.match(line)
        if m:
            key = m.group(1).strip().lower().replace("/", "_").replace(" ", "_")
            gps[key] = m.group(2).strip()

    if gps:
        print(f"    GPS fix: {gps.get('lat', '?')}, {gps.get('lon', '?')}")
    else:
        print("    No GPS data (module may not be connected)")
    return gps


# ---------------------------------------------------------------------------
# Parsers — Deauth & PMKID
# ---------------------------------------------------------------------------

# sniffdeauth: -65 Ch: 6 BSSID: aa:bb:cc:dd:ee:ff -> ff:ff:ff:ff:ff:ff
RE_DEAUTH = re.compile(
    r"(-?\d+)\s+Ch:\s*(\d+)\s+BSSID:\s+([0-9a-fA-F:]{17})\s+->\s+([0-9a-fA-F:]{17})")

# sniffpmkid: Received EAPOL: aa:bb:cc:dd:ee:ff
RE_PMKID = re.compile(r"Received EAPOL:\s+([0-9a-fA-F:]{17})")


def scan_deauth(ser, duration):
    """Run sniffdeauth, parse live output."""
    print(f"[>] Sniffing deauth frames for {duration}s...")
    send_cmd(ser, "sniffdeauth")
    lines = read_lines(ser, duration)
    stop_scan(ser)

    deauths = []
    for line in lines:
        m = RE_DEAUTH.match(line)
        if m:
            deauths.append({
                "rssi": int(m.group(1)),
                "channel": int(m.group(2)),
                "source": m.group(3),
                "dest": m.group(4),
            })
    print(f"    Captured {len(deauths)} deauth frames")
    return deauths


def scan_pmkid(ser, duration):
    """Run sniffpmkid, parse live output."""
    print(f"[>] Sniffing PMKID/EAPOL for {duration}s...")
    send_cmd(ser, "sniffpmkid")
    lines = read_lines(ser, duration)
    stop_scan(ser)

    eapols = []
    for line in lines:
        m = RE_PMKID.search(line)
        if m:
            eapols.append({"mac": m.group(1)})
    print(f"    Captured {len(eapols)} EAPOL frames")
    return eapols
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('tools/marauder_report.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: add BT/GPS/deauth/PMKID scan parsers"
```

---

### Task 4: Build the scan orchestrator (main loop)

**Files:**
- Modify: `tools/marauder_report.py`

**Step 1: Replace the placeholder in `__main__` with the orchestrator**

Replace everything after `print(f"[*] Connected. Starting scan suite...")` in the `__main__` block:

```python
    # Determine which scans to run
    if args.scans == "all":
        scan_list = {"wifi", "bt", "probe", "deauth", "pmkid", "gps"}
    else:
        scan_list = set(s.strip() for s in args.scans.split(","))

    results = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "port": port,
        "aps": [],
        "stations": [],
        "probes": {"live": [], "unique_ssids": []},
        "bt_devices": [],
        "gps": {},
        "deauths": [],
        "eapols": [],
    }

    try:
        if "wifi" in scan_list:
            results["aps"] = scan_aps(ser, args.ap_time)
            results["stations"] = scan_stations(ser, args.sta_time)

        if "probe" in scan_list:
            results["probes"] = scan_probes(ser, args.probe_time)

        if "bt" in scan_list:
            results["bt_devices"] = scan_bt(ser, args.bt_time)

        if "gps" in scan_list:
            results["gps"] = read_gps(ser, args.gps_time)

        if "deauth" in scan_list:
            results["deauths"] = scan_deauth(ser, args.deauth_time)

        if "pmkid" in scan_list:
            results["eapols"] = scan_pmkid(ser, args.pmkid_time)

    except Exception as e:
        print(f"[!] Scan error: {e}")
        stop_scan(ser)
    finally:
        ser.close()

    # Generate reports
    os.makedirs(args.output, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = os.path.join(args.output, f"report_{ts}")

    md_path = base + ".md"
    html_path = base + ".html"

    md = generate_markdown(results)
    html = generate_html(results)

    with open(md_path, "w") as f:
        f.write(md)
    with open(html_path, "w") as f:
        f.write(html)

    print(f"\n[*] Reports saved:")
    print(f"    HTML: {html_path}")
    print(f"      MD: {md_path}")
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('tools/marauder_report.py').read()); print('OK')"`
Expected: Will fail because `generate_markdown` and `generate_html` don't exist yet — that's fine, we add them in the next task.

**Step 3: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: add scan orchestrator and main loop"
```

---

### Task 5: Generate markdown report

**Files:**
- Modify: `tools/marauder_report.py`

**Step 1: Add markdown report generator**

Add before the `__main__` block:

```python
# ---------------------------------------------------------------------------
# Report — Markdown
# ---------------------------------------------------------------------------

def generate_markdown(r):
    """Generate a markdown report from scan results dict."""
    lines = []
    lines.append(f"# Marauder Scan Report")
    lines.append(f"**Generated:** {r['timestamp']}  ")
    lines.append(f"**Port:** {r['port']}  ")
    if r["gps"]:
        lines.append(f"**GPS:** {r['gps'].get('lat', '?')}, {r['gps'].get('lon', '?')} "
                      f"(Sats: {r['gps'].get('sats', '?')}, Alt: {r['gps'].get('alt', '?')})")
    lines.append("")

    # WiFi APs
    if r["aps"]:
        lines.append("## WiFi Access Points")
        lines.append(f"*{len(r['aps'])} networks found*\n")
        lines.append("| # | ESSID | Channel | RSSI |")
        lines.append("|---|-------|---------|------|")
        for i, ap in enumerate(r["aps"], 1):
            lines.append(f"| {i} | {ap['essid']} | {ap['channel']} | {ap['rssi']} dBm |")
        lines.append("")

    # Stations
    if r["stations"]:
        lines.append("## Station Associations")
        total = sum(len(a["stations"]) for a in r["stations"])
        lines.append(f"*{total} clients across {len(r['stations'])} APs*\n")
        for ap in r["stations"]:
            if ap["stations"]:
                lines.append(f"### {ap['essid']} ({ap['rssi']} dBm)")
                for mac in ap["stations"]:
                    lines.append(f"- `{mac}`")
                lines.append("")

    # Probes
    if r["probes"]["live"]:
        lines.append("## Probe Requests")
        lines.append(f"*{len(r['probes']['live'])} requests, "
                      f"{len(r['probes']['unique_ssids'])} unique SSIDs*\n")
        lines.append("| RSSI | Ch | Client MAC | Requested SSID |")
        lines.append("|------|----|------------|----------------|")
        for p in r["probes"]["live"]:
            lines.append(f"| {p['rssi']} | {p['channel']} | `{p['client_mac']}` | {p['essid']} |")
        lines.append("")

    # Bluetooth
    if r["bt_devices"]:
        lines.append("## Bluetooth Devices")
        lines.append(f"*{len(r['bt_devices'])} devices found*\n")
        lines.append("| # | Device | RSSI |")
        lines.append("|---|--------|------|")
        for i, d in enumerate(r["bt_devices"], 1):
            lines.append(f"| {i} | {d['name']} | {d['rssi']} dBm |")
        lines.append("")

    # Deauths
    if r["deauths"]:
        lines.append("## Deauth Activity")
        lines.append(f"*{len(r['deauths'])} deauth frames captured*\n")
        lines.append("| RSSI | Ch | Source | Destination |")
        lines.append("|------|----|--------|-------------|")
        for d in r["deauths"]:
            lines.append(f"| {d['rssi']} | {d['channel']} | `{d['source']}` | `{d['dest']}` |")
        lines.append("")

    # EAPOL/PMKID
    if r["eapols"]:
        lines.append("## EAPOL/PMKID Captures")
        lines.append(f"*{len(r['eapols'])} EAPOL frames captured*\n")
        for e in r["eapols"]:
            lines.append(f"- `{e['mac']}`")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by marauder_report.py*")
    return "\n".join(lines)
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('tools/marauder_report.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: add markdown report generator"
```

---

### Task 6: Generate HTML report

**Files:**
- Modify: `tools/marauder_report.py`

**Step 1: Add HTML report generator**

Add after `generate_markdown`:

```python
# ---------------------------------------------------------------------------
# Report — HTML
# ---------------------------------------------------------------------------

def generate_html(r):
    """Generate a dark-themed HTML report from scan results dict."""

    def table(headers, rows):
        h = "".join(f"<th>{c}</th>" for c in headers)
        body = ""
        for row in rows:
            body += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>\n"
        return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"

    def rssi_bar(rssi):
        """Visual RSSI strength indicator."""
        pct = max(0, min(100, (rssi + 100) * 2))  # -100=0%, -50=100%
        if pct > 66:
            color = "#00ff41"
        elif pct > 33:
            color = "#ffaa00"
        else:
            color = "#ff4444"
        return (f'<div class="rssi-bar"><div class="rssi-fill" '
                f'style="width:{pct}%;background:{color}"></div>'
                f'<span>{rssi} dBm</span></div>')

    sections = []

    # WiFi APs
    if r["aps"]:
        rows = [[i, ap["essid"], ap["channel"], rssi_bar(ap["rssi"])]
                for i, ap in enumerate(r["aps"], 1)]
        sections.append(f"""
        <div class="section">
            <h2>WiFi Access Points <span class="count">{len(r['aps'])}</span></h2>
            {table(["#", "ESSID", "Channel", "Signal"], rows)}
        </div>""")

    # Stations
    if r["stations"]:
        total = sum(len(a["stations"]) for a in r["stations"])
        sta_html = ""
        for ap in r["stations"]:
            if ap["stations"]:
                sta_html += f'<div class="ap-group"><h3>{ap["essid"]} ({ap["rssi"]} dBm)</h3><ul>'
                for mac in ap["stations"]:
                    sta_html += f"<li><code>{mac}</code></li>"
                sta_html += "</ul></div>"
        sections.append(f"""
        <div class="section">
            <h2>Station Associations <span class="count">{total} clients / {len(r['stations'])} APs</span></h2>
            {sta_html}
        </div>""")

    # Probes
    if r["probes"]["live"]:
        rows = [[p["rssi"], p["channel"], f'<code>{p["client_mac"]}</code>', p["essid"]]
                for p in r["probes"]["live"]]
        sections.append(f"""
        <div class="section">
            <h2>Probe Requests <span class="count">{len(r['probes']['live'])} captured</span></h2>
            {table(["RSSI", "Ch", "Client MAC", "Requested SSID"], rows)}
        </div>""")

    # Bluetooth
    if r["bt_devices"]:
        rows = [[i, d["name"], rssi_bar(d["rssi"])]
                for i, d in enumerate(r["bt_devices"], 1)]
        sections.append(f"""
        <div class="section">
            <h2>Bluetooth Devices <span class="count">{len(r['bt_devices'])}</span></h2>
            {table(["#", "Device", "Signal"], rows)}
        </div>""")

    # Deauths
    if r["deauths"]:
        rows = [[d["rssi"], d["channel"], f'<code>{d["source"]}</code>',
                 f'<code>{d["dest"]}</code>'] for d in r["deauths"]]
        sections.append(f"""
        <div class="section">
            <h2>Deauth Activity <span class="count">{len(r['deauths'])} frames</span></h2>
            {table(["RSSI", "Ch", "Source", "Destination"], rows)}
        </div>""")

    # EAPOL
    if r["eapols"]:
        eap_list = "".join(f"<li><code>{e['mac']}</code></li>" for e in r["eapols"])
        sections.append(f"""
        <div class="section">
            <h2>EAPOL/PMKID Captures <span class="count">{len(r['eapols'])}</span></h2>
            <ul>{eap_list}</ul>
        </div>""")

    # GPS header info
    gps_line = ""
    if r["gps"]:
        gps_line = (f'<div class="gps">GPS: {r["gps"].get("lat", "?")},'
                    f' {r["gps"].get("lon", "?")} | '
                    f'Sats: {r["gps"].get("sats", "?")} | '
                    f'Alt: {r["gps"].get("alt", "?")}m</div>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marauder Scan Report — {r['timestamp']}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace;
         padding: 20px; max-width: 1200px; margin: 0 auto; }}
  h1 {{ color: #00ff41; border-bottom: 2px solid #00ff41; padding-bottom: 10px;
       margin-bottom: 5px; font-size: 1.8em; }}
  .meta {{ color: #888; margin-bottom: 10px; }}
  .gps {{ color: #00ccff; margin-bottom: 20px; padding: 8px; background: #111;
          border-left: 3px solid #00ccff; }}
  .section {{ margin-bottom: 30px; }}
  h2 {{ color: #00ff41; margin-bottom: 10px; font-size: 1.3em; }}
  .count {{ color: #888; font-size: 0.7em; font-weight: normal; }}
  h3 {{ color: #ffaa00; margin: 8px 0 4px; font-size: 1em; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
  th {{ background: #1a1a1a; color: #00ff41; text-align: left; padding: 8px 12px;
       border-bottom: 2px solid #333; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #222; }}
  tr:hover {{ background: #111; }}
  code {{ color: #ffaa00; background: #1a1a1a; padding: 2px 6px; border-radius: 3px; }}
  ul {{ list-style: none; padding-left: 10px; }}
  li {{ padding: 3px 0; }}
  li::before {{ content: "> "; color: #00ff41; }}
  .ap-group {{ margin-bottom: 12px; padding-left: 10px;
              border-left: 2px solid #333; }}
  .rssi-bar {{ display: inline-flex; align-items: center; gap: 8px; }}
  .rssi-bar > div {{ width: 60px; height: 8px; background: #222; border-radius: 4px;
                    overflow: hidden; }}
  .rssi-fill {{ height: 100%; border-radius: 4px; }}
  .rssi-bar span {{ font-size: 0.85em; color: #aaa; }}
  footer {{ margin-top: 40px; padding-top: 10px; border-top: 1px solid #333;
           color: #555; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>// MARAUDER SCAN REPORT</h1>
<div class="meta">{r['timestamp']} &mdash; {r['port']}</div>
{gps_line}
{''.join(sections)}
<footer>Generated by marauder_report.py</footer>
</body>
</html>"""
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('tools/marauder_report.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: add dark-themed HTML report generator"
```

---

### Task 7: Test with mock data (no device needed)

**Files:**
- Modify: `tools/marauder_report.py`

**Step 1: Add a `--demo` flag for testing without a device**

Add to `build_parser()`:

```python
    p.add_argument("--demo", action="store_true",
                   help="Generate report with mock data (no device needed)")
```

Add a demo data function before `__main__`:

```python
def demo_results():
    """Return mock scan data for testing report generation."""
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "port": "/dev/demo",
        "aps": [
            {"index": 0, "channel": 6, "essid": "CoffeeShop_5G", "rssi": -42},
            {"index": 1, "channel": 1, "essid": "NETGEAR-Home", "rssi": -55},
            {"index": 2, "channel": 11, "essid": "xfinitywifi", "rssi": -68},
            {"index": 3, "channel": 6, "essid": "Hidden_Network", "rssi": -73},
            {"index": 4, "channel": 3, "essid": "IoT-Thermostat", "rssi": -81},
        ],
        "stations": [
            {"essid": "CoffeeShop_5G", "rssi": -42, "stations": [
                "aa:bb:cc:11:22:33", "dd:ee:ff:44:55:66"]},
            {"essid": "NETGEAR-Home", "rssi": -55, "stations": [
                "11:22:33:aa:bb:cc"]},
        ],
        "probes": {
            "live": [
                {"rssi": -50, "channel": 6, "client_mac": "aa:bb:cc:11:22:33",
                 "essid": "MyHomeWifi"},
                {"rssi": -65, "channel": 1, "client_mac": "dd:ee:ff:44:55:66",
                 "essid": "WorkNetwork"},
                {"rssi": -72, "channel": 11, "client_mac": "11:22:33:aa:bb:cc",
                 "essid": ""},
            ],
            "unique_ssids": ["MyHomeWifi", "WorkNetwork"],
        },
        "bt_devices": [
            {"name": "iPhone-Johns", "rssi": -45},
            {"name": "Galaxy Buds Pro", "rssi": -58},
            {"name": "aa:bb:cc:dd:ee:01", "rssi": -77},
        ],
        "gps": {"fix": "3D", "sats": "8", "lat": "37.7749",
                "lon": "-122.4194", "alt": "15.2", "accuracy": "3.5"},
        "deauths": [
            {"rssi": -55, "channel": 6, "source": "de:ad:be:ef:00:01",
             "dest": "ff:ff:ff:ff:ff:ff"},
        ],
        "eapols": [
            {"mac": "aa:bb:cc:11:22:33"},
        ],
    }
```

Update `__main__` to handle `--demo` — add right after the args parsing, before the port check:

```python
    if args.demo:
        print("[*] Demo mode — generating report with mock data...")
        results = demo_results()
        os.makedirs(args.output, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        base = os.path.join(args.output, f"report_{ts}")
        md_path = base + ".md"
        html_path = base + ".html"
        with open(md_path, "w") as f:
            f.write(generate_markdown(results))
        with open(html_path, "w") as f:
            f.write(generate_html(results))
        print(f"\n[*] Demo reports saved:")
        print(f"    HTML: {html_path}")
        print(f"      MD: {md_path}")
        sys.exit(0)
```

**Step 2: Run demo mode**

Run: `python tools/marauder_report.py --demo --output /tmp/marauder_test`
Expected: Two files created in `/tmp/marauder_test/`, script prints paths.

**Step 3: Verify HTML opens in browser and looks good**

Run: `xdg-open /tmp/marauder_test/report_*.html` (or just check the file exists and has content)

**Step 4: Commit**

```bash
git add tools/marauder_report.py
git commit -m "feat: add --demo mode for testing report generation without device"
```

---

## Summary

| Task | What | Commit message |
|------|------|---------------|
| 1 | CLI scaffold + serial helpers | `feat: scaffold marauder report script with CLI and serial helpers` |
| 2 | WiFi AP/station/probe parsers | `feat: add WiFi AP/station/probe scan + parsing` |
| 3 | BT/GPS/deauth/PMKID parsers | `feat: add BT/GPS/deauth/PMKID scan parsers` |
| 4 | Main orchestrator loop | `feat: add scan orchestrator and main loop` |
| 5 | Markdown report generator | `feat: add markdown report generator` |
| 6 | HTML report generator (dark theme) | `feat: add dark-themed HTML report generator` |
| 7 | Demo mode for testing | `feat: add --demo mode for testing report generation without device` |
