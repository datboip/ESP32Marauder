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
    read_lines(ser, duration)
    stop_scan(ser)

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

    send_cmd(ser, "list -p")
    list_lines = read_lines(ser, 5)
    unique_ssids = []
    for line in list_lines:
        m = RE_PROBE.match(line)
        if m:
            unique_ssids.append(m.group(2).strip())

    print(f"    Captured {len(probes_live)} probe requests ({len(unique_ssids)} unique SSIDs)")
    return {"live": probes_live, "unique_ssids": unique_ssids}


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


# ---------------------------------------------------------------------------
# Report — Markdown
# ---------------------------------------------------------------------------

def generate_markdown(r):
    """Generate a markdown report from scan results dict."""
    lines = []
    lines.append("# Marauder Scan Report")
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
<title>Marauder Scan Report &mdash; {r['timestamp']}</title>
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


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def demo_results():
    """Return scan data from Harrah's Cherokee Casino wardrive."""
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "port": "/dev/demo",
        "aps": [
            {"index": 0, "channel": 1, "essid": "CarLinkAP132", "rssi": -33, "mac": "AA:BB:CC:01:02:03", "auth": "[WPA2_PSK]"},
            {"index": 1, "channel": 4, "essid": "50:b1:27:13:f6:b5", "rssi": -36, "mac": "50:B1:27:13:F6:B5", "auth": ""},
            {"index": 2, "channel": 2, "essid": "2e:03:9a:d0:79:76", "rssi": -38, "mac": "2E:03:9A:D0:79:76", "auth": ""},
            {"index": 3, "channel": 5, "essid": "86:ea:04:7a:f7:00", "rssi": -48, "mac": "86:EA:04:7A:F7:00", "auth": ""},
            {"index": 4, "channel": 5, "essid": "0e:18:7d:94:d9:4e", "rssi": -49, "mac": "0E:18:7D:94:D9:4E", "auth": ""},
            {"index": 5, "channel": 8, "essid": "NETGEAR44", "rssi": -54, "mac": "AA:BB:CC:05:06:07", "auth": "[WPA2_PSK]"},
            {"index": 6, "channel": 1, "essid": "Frontier Motor Lodge", "rssi": -55, "mac": "AA:BB:CC:08:09:0A", "auth": "[WPA2_PSK]"},
            {"index": 7, "channel": 6, "essid": "Indian Hills RV WIFI", "rssi": -56, "mac": "AA:BB:CC:0B:0C:0D", "auth": "[WPA2_PSK]"},
            {"index": 8, "channel": 1, "essid": "che_hccr", "rssi": -57, "mac": "CC:1B:5A:59:E1:B3", "auth": "[WPA2_PSK]"},
            {"index": 9, "channel": 6, "essid": "che_hccr", "rssi": -60, "mac": "CC:1B:5A:5A:1F:A3", "auth": "[WPA2_PSK]"},
            {"index": 10, "channel": 9, "essid": "HCR-24S-AP2", "rssi": -60, "mac": "AA:BB:CC:0E:0F:10", "auth": "[WPA_WPA2_PSK]"},
            {"index": 11, "channel": 1, "essid": "Frontier Motor Lodge", "rssi": -61, "mac": "AA:BB:CC:11:12:13", "auth": "[WPA2_PSK]"},
            {"index": 12, "channel": 6, "essid": "My VW 8851", "rssi": -62, "mac": "AA:BB:CC:14:15:16", "auth": "[WPA2_PSK]"},
            {"index": 13, "channel": 1, "essid": "McDonalds Free WiFi", "rssi": -62, "mac": "AA:BB:CC:17:18:19", "auth": "[OPEN]"},
            {"index": 14, "channel": 1, "essid": "eBOS", "rssi": -62, "mac": "AA:BB:CC:1A:1B:1C", "auth": "[OPEN]"},
            {"index": 15, "channel": 6, "essid": "DIRECT-E2-HP OfficeJet Pro 8710", "rssi": -65, "mac": "AA:BB:CC:1D:1E:1F", "auth": "[WPA2_PSK]"},
            {"index": 16, "channel": 1, "essid": "Tiffers", "rssi": -65, "mac": "AA:BB:CC:20:21:22", "auth": "[WPA2_WPA3_PSK]"},
            {"index": 17, "channel": 11, "essid": "Willis", "rssi": -65, "mac": "AA:BB:CC:23:24:25", "auth": "[WPA2_PSK]"},
            {"index": 18, "channel": 8, "essid": "441BB-24M-AP1", "rssi": -65, "mac": "AA:BB:CC:26:27:28", "auth": "[WPA2_PSK]"},
            {"index": 19, "channel": 6, "essid": "STARLINK", "rssi": -65, "mac": "AA:BB:CC:29:2A:2B", "auth": "[WPA2_PSK]"},
            {"index": 20, "channel": 6, "essid": "Che_Spa", "rssi": -68, "mac": "70:CA:97:F4:20:08", "auth": "[WPA2_PSK]"},
            {"index": 21, "channel": 1, "essid": "Caesar_Resorts", "rssi": -72, "mac": "28:B3:71:03:25:49", "auth": "[OPEN]"},
            {"index": 22, "channel": 11, "essid": "CHEVIPHOST", "rssi": -73, "mac": "28:B3:71:46:8A:98", "auth": "[WPA2_PSK]"},
            {"index": 23, "channel": 6, "essid": "CHEVIPHOST", "rssi": -74, "mac": "8C:7A:15:60:29:43", "auth": "[WPA2_PSK]"},
            {"index": 24, "channel": 6, "essid": "DELTA", "rssi": -74, "mac": "8C:7A:15:60:29:44", "auth": "[WPA2]"},
            {"index": 25, "channel": 11, "essid": "Staycast-Device", "rssi": -74, "mac": "28:B3:71:C2:4F:B8", "auth": "[WPA2_PSK]"},
            {"index": 26, "channel": 6, "essid": "che_event", "rssi": -75, "mac": "8C:7A:15:60:29:42", "auth": "[WPA2_PSK]"},
            {"index": 27, "channel": 6, "essid": "Harrahs_CONFERENCE", "rssi": -75, "mac": "8C:7A:15:60:29:41", "auth": "[OPEN]"},
            {"index": 28, "channel": 1, "essid": "che_assoc", "rssi": -75, "mac": "28:B3:71:82:42:28", "auth": "[WPA2_PSK]"},
            {"index": 29, "channel": 1, "essid": "Staycast-Device", "rssi": -75, "mac": "28:B3:71:C2:04:48", "auth": "[WPA2_PSK]"},
            {"index": 30, "channel": 11, "essid": "DELTA", "rssi": -75, "mac": "28:B3:71:42:4F:B9", "auth": "[WPA2]"},
            {"index": 31, "channel": 11, "essid": "che_event", "rssi": -75, "mac": "28:B3:71:83:53:48", "auth": "[WPA2_PSK]"},
            {"index": 32, "channel": 6, "essid": "che_assoc", "rssi": -75, "mac": "CC:1B:5A:5A:1F:A4", "auth": "[WPA2_PSK]"},
            {"index": 33, "channel": 1, "essid": "CHEVIPHOST", "rssi": -76, "mac": "28:B3:71:42:04:48", "auth": "[WPA2_PSK]"},
            {"index": 34, "channel": 1, "essid": "Caesar_Resorts", "rssi": -76, "mac": "28:B3:71:02:04:49", "auth": "[OPEN]"},
            {"index": 35, "channel": 1, "essid": "DELTA", "rssi": -76, "mac": "28:B3:71:42:04:49", "auth": "[WPA2]"},
            {"index": 36, "channel": 11, "essid": "Caesar_Resorts", "rssi": -76, "mac": "28:B3:71:02:4F:B9", "auth": "[OPEN]"},
            {"index": 37, "channel": 11, "essid": "DELTA", "rssi": -76, "mac": "28:B3:71:03:53:49", "auth": "[WPA2]"},
            {"index": 38, "channel": 1, "essid": "che_assoc", "rssi": -77, "mac": "F0:6F:CE:50:82:F1", "auth": "[WPA2_PSK]"},
            {"index": 39, "channel": 1, "essid": "DELTA", "rssi": -77, "mac": "28:B3:71:03:25:44", "auth": "[WPA2]"},
            {"index": 40, "channel": 1, "essid": "CHEVIPHOST", "rssi": -77, "mac": "28:B3:71:82:04:43", "auth": "[WPA2_PSK]"},
            {"index": 41, "channel": 6, "essid": "HOTSOS", "rssi": -77, "mac": "00:03:52:C5:1E:F1", "auth": "[WPA2_PSK]"},
            {"index": 42, "channel": 1, "essid": "DELTA", "rssi": -77, "mac": "28:B3:71:82:42:29", "auth": "[WPA2]"},
            {"index": 43, "channel": 1, "essid": "che_assoc", "rssi": -77, "mac": "28:B3:71:82:04:48", "auth": "[WPA2_PSK]"},
            {"index": 44, "channel": 6, "essid": "che_assoc", "rssi": -77, "mac": "CC:1B:5A:59:E1:B4", "auth": "[WPA2_PSK]"},
        ],
        "stations": [
            {"essid": "CHEVIPHOST", "rssi": -73, "stations": [
                "28:B3:71:46:8A:98", "8C:7A:15:60:29:43",
                "28:B3:71:C3:53:48", "28:B3:71:42:04:48"]},
            {"essid": "Caesar_Resorts", "rssi": -72, "stations": [
                "28:B3:71:03:25:49", "28:B3:71:02:04:49",
                "28:B3:71:02:4F:B9"]},
            {"essid": "Che_Spa", "rssi": -68, "stations": [
                "70:CA:97:F4:20:08"]},
            {"essid": "DELTA", "rssi": -74, "stations": [
                "8C:7A:15:60:29:44", "28:B3:71:42:4F:B9",
                "28:B3:71:03:53:49", "28:B3:71:42:04:49"]},
            {"essid": "HOTSOS", "rssi": -77, "stations": [
                "00:03:52:C5:1E:F1"]},
            {"essid": "Harrahs_CONFERENCE", "rssi": -75, "stations": [
                "8C:7A:15:60:29:41"]},
            {"essid": "Staycast-Device", "rssi": -74, "stations": [
                "28:B3:71:C2:4F:B8", "28:B3:71:C2:04:48"]},
            {"essid": "che_assoc", "rssi": -75, "stations": [
                "28:B3:71:82:42:28", "28:B3:71:82:04:48",
                "CC:1B:5A:5A:1F:A4", "F0:6F:CE:50:82:F1"]},
            {"essid": "che_event", "rssi": -75, "stations": [
                "28:B3:71:83:53:48", "8C:7A:15:60:29:42"]},
            {"essid": "che_hccr", "rssi": -57, "stations": [
                "CC:1B:5A:59:E1:B3", "CC:1B:5A:5A:1F:A3"]},
        ],
        "probes": {
            "live": [
                {"rssi": -55, "channel": 6, "client_mac": "28:B3:71:82:42:28",
                 "essid": "Harrahs_GUEST"},
                {"rssi": -62, "channel": 1, "client_mac": "8C:7A:15:60:29:41",
                 "essid": "che_edr"},
                {"rssi": -68, "channel": 11, "client_mac": "70:CA:97:F4:20:08",
                 "essid": "HarrahsRoomInternet"},
                {"rssi": -71, "channel": 6, "client_mac": "F0:6F:CE:50:82:F1",
                 "essid": ""},
                {"rssi": -74, "channel": 1, "client_mac": "CC:1B:5A:59:E1:B3",
                 "essid": "Harrahs_LOBBY"},
            ],
            "unique_ssids": ["Harrahs_GUEST", "che_edr",
                             "HarrahsRoomInternet", "Harrahs_LOBBY"],
        },
        "bt_devices": [
            {"name": "72:39:90:76:6C:83", "rssi": -43},
            {"name": "5B:93:72:ED:E5:3A", "rssi": -43},
            {"name": "4E:75:5C:AC:67:6A", "rssi": -46},
            {"name": "47:2F:73:AA:8E:0F", "rssi": -46},
            {"name": "FC:D7:3C:76:91:AF", "rssi": -48},
            {"name": "F2:B5:28:C3:4F:2E", "rssi": -48},
            {"name": "60:54:F5:E0:2E:E4", "rssi": -52},
            {"name": "E1:EC:B3:16:1E:FA", "rssi": -53},
            {"name": "42:16:BD:59:8C:3D", "rssi": -53},
            {"name": "E3:7A:9D:68:37:42", "rssi": -65},
            {"name": "67:C3:B3:A5:25:A4", "rssi": -71},
            {"name": "58:C6:CC:66:B7:C1", "rssi": -71},
            {"name": "F0:C8:14:3C:95:3F", "rssi": -71},
            {"name": "70:1F:72:63:60:2B", "rssi": -73},
            {"name": "F5:E5:A0:BF:6C:BA", "rssi": -74},
            {"name": "7B:2A:E7:45:FD:0C", "rssi": -75},
            {"name": "EA:8B:51:FC:33:99", "rssi": -75},
            {"name": "13:ED:1E:29:7F:CF", "rssi": -75},
            {"name": "5B:C4:41:7B:01:68", "rssi": -75},
            {"name": "E1:48:CC:F8:1E:FB", "rssi": -76},
            {"name": "08:9D:88:90:CF:22", "rssi": -76},
            {"name": "5E:88:65:1D:F9:0F", "rssi": -76},
            {"name": "62:63:8A:E7:59:42", "rssi": -77},
            {"name": "7D:F5:11:6E:CF:19", "rssi": -77},
            {"name": "ED:01:E4:C2:AE:92", "rssi": -77},
        ],
        "gps": {"fix": "3D", "sats": "11", "lat": "35.4490",
                "lon": "-83.3150", "alt": "585.0", "accuracy": "2.8"},
        "deauths": [
            {"rssi": -62, "channel": 6, "source": "8C:7A:15:60:29:44",
             "dest": "ff:ff:ff:ff:ff:ff"},
            {"rssi": -71, "channel": 1, "source": "28:B3:71:03:25:49",
             "dest": "ff:ff:ff:ff:ff:ff"},
        ],
        "eapols": [
            {"mac": "28:B3:71:46:8A:98"},
            {"mac": "8C:7A:15:60:29:43"},
        ],
    }


# ---------------------------------------------------------------------------
# Main
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
    p.add_argument("--demo", action="store_true",
                   help="Generate report with mock data (no device needed)")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()

    # Demo mode — no device needed
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

    # Real mode — connect to device
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

    print("[*] Connected. Starting scan suite...")

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
