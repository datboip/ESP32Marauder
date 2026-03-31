#!/usr/bin/env python3
"""Marauder Web Dashboard — Flask UI for ESP32 Marauder scan report tool.

Connects to an ESP32 Marauder over serial, runs scans via a web interface,
streams results live via SSE, and generates HTML/Markdown reports.

All HTML/CSS/JS is inline — single-file Flask app.
"""

import argparse
import glob
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

# Ensure we can import marauder_report from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, request, send_from_directory

import marauder_report as mr

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Global state protected by locks
_serial_lock = threading.Lock()
_results_lock = threading.Lock()
_state = {
    "ser": None,
    "connected": False,
    "scanning": False,
    "scan_type": None,
    "run_all_progress": None,  # e.g. "WiFi APs (2/7)"
    "results": {
        "timestamp": None,
        "port": None,
        "aps": [],
        "stations": [],
        "probes": {"live": [], "unique_ssids": []},
        "bt_devices": [],
        "gps": {},
        "deauths": [],
        "eapols": [],
    },
}

# SSE subscribers — each listener gets its own Queue
_sse_queues = []
_sse_lock = threading.Lock()

REPORTS_DIR = "./reports"

# ---------------------------------------------------------------------------
# Monkey-patch marauder_report.read_lines to stream each line to SSE
# ---------------------------------------------------------------------------
_original_read_lines = mr.read_lines

def _streaming_read_lines(ser, duration, stop_early=None):
    """Wrapper that publishes each serial line to SSE as it arrives."""
    lines = []
    deadline = time.time() + duration
    while time.time() < deadline:
        raw = ser.readline()
        if raw:
            line = raw.decode(errors="replace").strip()
            if line:
                lines.append(line)
                # Stream to UI — skip echo lines (start with #)
                if not line.startswith("#"):
                    _sse_publish("log", line)
                if stop_early and re.search(stop_early, line):
                    break
    return lines

mr.read_lines = _streaming_read_lines

# Scan type registry: key -> (display_name, scan_function, result_key, default_duration, cli_cmd)
SCAN_TYPES = {
    "aps":      ("WiFi APs",   mr.scan_aps,      "aps",        15, "scanap"),
    "stations": ("Stations",   mr.scan_stations,  "stations",   20, "scansta"),
    "probes":   ("Probes",     mr.scan_probes,    "probes",     30, "sniffprobe"),
    "bt":       ("Bluetooth",  mr.scan_bt,        "bt_devices", 30, "sniffbt"),
    "gps":      ("GPS",        mr.read_gps,       "gps",        5,  "gpsdata"),
    "deauth":   ("Deauth",     mr.scan_deauth,    "deauths",    20, "sniffdeauth"),
    "pmkid":    ("PMKID",      mr.scan_pmkid,     "eapols",     20, "sniffpmkid"),
}

# Background scan thread handle
_scan_thread = None


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse_publish(event_type, data):
    """Push an event to all SSE listeners."""
    msg = json.dumps(data)
    with _sse_lock:
        dead = []
        for i, q in enumerate(_sse_queues):
            try:
                q.put_nowait((event_type, msg))
            except queue.Full:
                dead.append(i)
        for i in reversed(dead):
            _sse_queues.pop(i)


def _sse_format(event_type, data):
    """Format a single SSE message."""
    return f"event: {event_type}\ndata: {data}\n\n"


# ---------------------------------------------------------------------------
# Results summary helper
# ---------------------------------------------------------------------------

def _results_summary():
    with _results_lock:
        r = _state["results"]
        total_stations = sum(len(a.get("stations", [])) for a in r["stations"])
        probe_count = len(r["probes"]["live"]) if isinstance(r["probes"], dict) else 0
        return {
            "aps": len(r["aps"]),
            "stations": total_stations,
            "probes": probe_count,
            "bt_devices": len(r["bt_devices"]),
            "gps": bool(r["gps"]),
            "deauths": len(r["deauths"]),
            "eapols": len(r["eapols"]),
        }


# ---------------------------------------------------------------------------
# Scan worker
# ---------------------------------------------------------------------------

def _run_scan(scan_key, duration):
    """Run a single scan in the background thread."""
    display_name, scan_fn, result_key, _, cli_cmd = SCAN_TYPES[scan_key]

    _state["scanning"] = True
    _state["scan_type"] = scan_key

    _sse_publish("scan_start", {"type": scan_key, "name": display_name, "duration": duration})
    _sse_publish("log", f"[>] Starting {display_name} scan for {duration}s...")

    try:
        with _serial_lock:
            ser = _state["ser"]
            if ser is None or not ser.is_open:
                raise RuntimeError("Not connected")
            result = scan_fn(ser, duration)

        with _results_lock:
            _state["results"][result_key] = result
            _state["results"]["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        _sse_publish("scan_complete", {"type": scan_key, "name": display_name})
        _sse_publish("result", {"type": scan_key, "summary": _results_summary()})
        _sse_publish("log", f"[+] {display_name} scan complete")

    except Exception as e:
        _sse_publish("error", {"message": str(e), "type": scan_key})
        _sse_publish("log", f"[!] Error in {display_name}: {e}")

    finally:
        _state["scanning"] = False
        _state["scan_type"] = None
        _sse_publish("scan_stop", {"type": scan_key})


def _run_all_scans(durations):
    """Run all scan types sequentially."""
    order = ["aps", "stations", "probes", "bt", "gps", "deauth", "pmkid"]
    total = len(order)

    _state["scanning"] = True
    _sse_publish("log", "[*] Starting full scan suite...")

    for idx, key in enumerate(order, 1):
        display_name = SCAN_TYPES[key][0]
        _state["scan_type"] = key
        _state["run_all_progress"] = f"{display_name} ({idx}/{total})"
        dur = durations.get(key, SCAN_TYPES[key][3])

        _sse_publish("scan_start", {
            "type": key, "name": display_name, "duration": dur,
            "progress": f"{idx}/{total}"
        })
        _sse_publish("log", f"[>] [{idx}/{total}] Starting {display_name} for {dur}s...")

        try:
            with _serial_lock:
                ser = _state["ser"]
                if ser is None or not ser.is_open:
                    raise RuntimeError("Not connected")
                scan_fn = SCAN_TYPES[key][1]
                result_key = SCAN_TYPES[key][2]
                result = scan_fn(ser, dur)

            with _results_lock:
                _state["results"][result_key] = result
                _state["results"]["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            _sse_publish("scan_complete", {"type": key, "name": display_name})
            _sse_publish("result", {"type": key, "summary": _results_summary()})
            _sse_publish("log", f"[+] {display_name} complete")

        except Exception as e:
            _sse_publish("error", {"message": str(e), "type": key})
            _sse_publish("log", f"[!] Error in {display_name}: {e}")
            # If not connected, abort the rest
            if "Not connected" in str(e):
                break

        _sse_publish("scan_stop", {"type": key})

    _state["scanning"] = False
    _state["scan_type"] = None
    _state["run_all_progress"] = None
    _sse_publish("log", "[*] Full scan suite finished")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(force=True)
    port = data.get("port", "").strip()
    baud = int(data.get("baud", 115200))

    if not port or port == "auto":
        port = mr.find_serial_port()
        if not port:
            return jsonify({"ok": False, "error": "No serial port found"}), 400

    try:
        with _serial_lock:
            if _state["ser"] and _state["ser"].is_open:
                _state["ser"].close()
            ser = mr.connect(port, baud)
            _state["ser"] = ser
            _state["connected"] = True
            _state["results"]["port"] = port
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _sse_publish("log", f"[+] Connected to {port} @ {baud}")
    return jsonify({"ok": True, "port": port, "baud": baud})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    with _serial_lock:
        if _state["ser"] and _state["ser"].is_open:
            try:
                mr.stop_scan(_state["ser"])
            except Exception:
                pass
            _state["ser"].close()
        _state["ser"] = None
        _state["connected"] = False
        _state["scanning"] = False
        _state["scan_type"] = None

    _sse_publish("log", "[-] Disconnected")
    return jsonify({"ok": True})


@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    global _scan_thread
    if not _state["connected"]:
        return jsonify({"ok": False, "error": "Not connected"}), 400
    if _state["scanning"]:
        return jsonify({"ok": False, "error": "Scan already running"}), 409

    data = request.get_json(force=True)
    scan_key = data.get("type", "")
    if scan_key not in SCAN_TYPES:
        return jsonify({"ok": False, "error": f"Unknown scan type: {scan_key}"}), 400

    duration = int(data.get("duration", SCAN_TYPES[scan_key][3]))
    _scan_thread = threading.Thread(target=_run_scan, args=(scan_key, duration), daemon=True)
    _scan_thread.start()
    return jsonify({"ok": True, "type": scan_key, "duration": duration})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    if not _state["connected"]:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    try:
        with _serial_lock:
            if _state["ser"] and _state["ser"].is_open:
                mr.stop_scan(_state["ser"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    _sse_publish("log", "[!] Stop scan sent")
    return jsonify({"ok": True})


@app.route("/api/scan/all", methods=["POST"])
def api_scan_all():
    global _scan_thread
    if not _state["connected"]:
        return jsonify({"ok": False, "error": "Not connected"}), 400
    if _state["scanning"]:
        return jsonify({"ok": False, "error": "Scan already running"}), 409

    data = request.get_json(force=True) if request.data else {}
    durations = data.get("durations", {})
    _scan_thread = threading.Thread(target=_run_all_scans, args=(durations,), daemon=True)
    _scan_thread.start()
    return jsonify({"ok": True})


@app.route("/api/report/generate", methods=["POST"])
def api_report_generate():
    with _results_lock:
        results = dict(_state["results"])
        if not results.get("timestamp"):
            results["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not results.get("port"):
            results["port"] = "unknown"

    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = os.path.join(REPORTS_DIR, f"report_{ts}")

    md_path = base + ".md"
    html_path = base + ".html"

    with open(md_path, "w") as f:
        f.write(mr.generate_markdown(results))
    with open(html_path, "w") as f:
        f.write(mr.generate_html(results))

    _sse_publish("log", f"[+] Report saved: report_{ts}")
    return jsonify({
        "ok": True,
        "html": os.path.basename(html_path),
        "md": os.path.basename(md_path),
    })


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Send scan results to local Ollama for plain-English analysis."""
    _sse_publish("log", "[*] Sending scan data to Ollama for analysis...")

    with _results_lock:
        r = dict(_state["results"])

    # OUI vendor lookup for MAC addresses
    _OUI_DB = {
        "AC:67:06": "Ruckus", "D8:38:FC": "Ruckus", "74:67:F7": "Ruckus",
        "70:DF:2F": "Ruckus", "C4:01:7C": "Ruckus", "EC:58:EA": "Ruckus",
        "B4:79:C8": "Ruckus", "00:25:C4": "Ruckus", "CC:1B:5A": "Ruckus",
        "A8:BD:27": "Aruba/HPE", "00:0B:86": "Aruba", "24:DE:C6": "Aruba",
        "6C:F3:7F": "Aruba", "D8:C7:C8": "Aruba", "20:4C:03": "Aruba",
        "84:23:88": "Aruba", "8C:7A:15": "Aruba", "28:B3:71": "Aruba",
        "F0:6F:CE": "Aruba", "70:CA:97": "Aruba",
        "00:40:96": "Cisco", "00:1B:0D": "Cisco", "F4:CF:E2": "Cisco",
        "00:3A:7D": "Meraki", "00:18:0A": "Meraki", "AC:17:C8": "Meraki",
        "00:03:52": "Cisco", "50:C7:BF": "TP-Link", "60:32:B1": "TP-Link",
        "A4:97:33": "eero",
    }
    def _oui(mac):
        return _OUI_DB.get(mac[:8].upper(), "")

    # Build a detailed text summary for security audit
    summary_parts = []

    # Stats overview
    n_aps = len(r["aps"])
    n_open = sum(1 for a in r["aps"] if a.get("auth") in ("[OPEN]", "OPEN", ""))
    n_bt = len(r["bt_devices"])
    n_stations = sum(len(s.get("stations", [])) for s in r.get("stations", []))
    summary_parts.append(f"SCAN SUMMARY: {n_aps} APs ({n_open} OPEN), "
                         f"{n_stations} station associations, {n_bt} BLE devices")

    if r["aps"]:
        summary_parts.append("\nWiFi Access Points:")
        for ap in r["aps"]:
            vendor = _oui(ap.get("mac", "")) if ap.get("mac") else ""
            auth = ap.get("auth", "unknown")
            v_tag = f" [{vendor}]" if vendor else ""
            open_flag = " **OPEN/UNENCRYPTED**" if auth in ("[OPEN]", "OPEN", "") else ""
            summary_parts.append(
                f"  - {ap['essid']} (CH:{ap['channel']}, {ap['rssi']}dBm, "
                f"Auth:{auth}{v_tag}{open_flag})")

    if r["stations"]:
        summary_parts.append("\nStation Associations (clients connected to APs):")
        for ap in r["stations"]:
            if ap.get("stations"):
                macs_with_vendor = []
                for mac in ap["stations"]:
                    v = _oui(mac)
                    macs_with_vendor.append(f"{mac} [{v}]" if v else mac)
                summary_parts.append(
                    f"  - {ap['essid']} ({ap['rssi']}dBm): "
                    f"{len(ap['stations'])} clients")
                for m in macs_with_vendor:
                    summary_parts.append(f"      {m}")

    if r["probes"] and r["probes"].get("live"):
        summary_parts.append("\nProbe Requests (devices searching for networks):")
        for p in r["probes"]["live"]:
            ssid = p['essid'] or '(broadcast/hidden)'
            summary_parts.append(
                f"  - {p['client_mac']} probing for '{ssid}' (CH:{p['channel']})")

    if r["bt_devices"]:
        summary_parts.append(f"\nBluetooth Devices ({len(r['bt_devices'])}):")
        for d in r["bt_devices"]:
            summary_parts.append(f"  - {d['name']} ({d['rssi']}dBm)")

    if r["gps"]:
        summary_parts.append(
            f"\nGPS Location: {r['gps'].get('lat','?')}, {r['gps'].get('lon','?')} "
            f"(Sats:{r['gps'].get('sats','?')}, Alt:{r['gps'].get('alt','?')}m)")

    if r["deauths"]:
        summary_parts.append(f"\nDeauth Frames: {len(r['deauths'])} captured")
        for d in r["deauths"]:
            src_v = _oui(d['source'])
            src_tag = f" [{src_v}]" if src_v else ""
            summary_parts.append(
                f"  - {d['source']}{src_tag} -> {d['dest']} (CH:{d['channel']})")

    if r["eapols"]:
        summary_parts.append(f"\nEAPOL/PMKID Captures: {len(r['eapols'])}")
        for e in r["eapols"]:
            summary_parts.append(f"  - {e['mac']}")

    scan_text = "\n".join(summary_parts)
    if not scan_text.strip():
        return jsonify({"ok": False, "error": "No scan data to analyze"})

    # Load audit context file if available
    audit_context = ""
    context_path = os.path.join(os.path.dirname(__file__), "audit_context.md")
    if os.path.exists(context_path):
        with open(context_path) as f:
            audit_context = f.read()

    context_block = ""
    if audit_context:
        context_block = f"""

PRIOR AUDIT INTELLIGENCE (use this to enrich your analysis — reference specific findings, numbers, and context from this document):
{audit_context}
"""

    prompt = f"""You are a wireless penetration tester writing a security assessment. You have scan data from an ESP32 Marauder device AND prior audit intelligence about this facility. Cross-reference the scan data against the audit context to produce a thorough, specific report.

CRITICAL INSTRUCTIONS:
- Do NOT hallucinate findings. Only report what is actually in the scan data or audit context.
- If the audit context mentions something not in the scan data, say "per prior audit" when referencing it.
- Cite exact SSIDs, MACs, auth modes, and vendor OUIs from the data.
- Rate every finding: CRITICAL / HIGH / MEDIUM / LOW

Your report MUST include:

## 1. Target Identification
Identify the facility. Map SSIDs to their function using the audit context. Group by: guest-facing, internal operations, third-party/nearby.

## 2. Open Network Exposure (CRITICAL)
List every OPEN/unencrypted network in the scan data with its SSID, AP count, and purpose. Explain why open WiFi at a casino is especially dangerous (guest credentials, evil twin attacks, passive capture). Reference the Caesar_Resorts and Harrahs_CONFERENCE findings specifically.

## 3. Internal Network Disclosure
Map each internal SSID to what it reveals about the organization. Highlight the worst exposures: surveillance (SurvDept121), external auditors (che_extaudit), gaming systems (TBLSIGN, DELTA), executive (che_exec). Explain why PSK auth on all internal networks is a finding.

## 4. Infrastructure Analysis
Identify vendors from OUI prefixes in the MAC addresses. Note any end-of-life hardware (Colubris/00:03:52). Comment on the physical AP count vs virtual BSSID count.

## 5. Active Threats
Analyze deauth frames and EAPOL captures. Are the source MACs infrastructure or rogue? What does EAPOL capture mean for WPA key security?

## 6. Probe Request Intelligence
What networks are devices probing for? What does this reveal about internal network names not actively broadcasting?

## 7. Risk Summary Table
| Finding | Severity | Details |
Format as a proper table.

## 8. Recommendations
Specific, actionable steps. Reference WPA3-OWE for guest networks, 802.1X migration for internal, SSID renaming, hardware replacement.

Write in a direct, professional tone. Use markdown. Be specific — cite SSIDs, MACs, auth modes, vendors by name.
{context_block}
LIVE SCAN DATA:
{scan_text}"""

    # Call Ollama API (streaming to avoid timeout on large prompts)
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({
                "model": "llama3",
                "prompt": prompt,
                "stream": True,
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        chunks = []
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("response", "")
                if token:
                    chunks.append(token)
                if chunk.get("done"):
                    break
        analysis = "".join(chunks)

        _sse_publish("log", "[+] Ollama analysis complete")
        return jsonify({"ok": True, "analysis": analysis})

    except urllib.error.URLError:
        _sse_publish("log", "[!] Ollama not running — start it with: ollama serve")
        return jsonify({"ok": False, "error": "Cannot connect to Ollama. Is it running? (ollama serve)"}), 503
    except Exception as e:
        _sse_publish("log", f"[!] Ollama error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/report/<filename>", methods=["DELETE"])
def api_report_delete(filename):
    # Safety: only allow report_*.html / report_*.md
    if not filename.startswith("report_"):
        return jsonify({"ok": False, "error": "Invalid filename"}), 400

    base = os.path.splitext(filename)[0]
    deleted = []
    for ext in (".html", ".md"):
        path = os.path.join(REPORTS_DIR, base + ext)
        if os.path.exists(path):
            os.remove(path)
            deleted.append(base + ext)

    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/status")
def api_status():
    return jsonify({
        "connected": _state["connected"],
        "scanning": _state["scanning"],
        "scan_type": _state["scan_type"],
        "run_all_progress": _state["run_all_progress"],
        "results_summary": _results_summary(),
    })


@app.route("/api/stream")
def api_stream():
    """SSE endpoint — clients connect here to receive live events."""
    q = queue.Queue(maxsize=256)
    with _sse_lock:
        _sse_queues.append(q)

    def generate():
        # Send initial status
        yield _sse_format("status", json.dumps({
            "connected": _state["connected"],
            "scanning": _state["scanning"],
            "summary": _results_summary(),
        }))
        # Send welcome log so feed isn't blank
        summary = _results_summary()
        has_data = any(v for k, v in summary.items() if k != "gps")
        if has_data:
            yield _sse_format("log", json.dumps(
                f"[*] Scan data loaded — {summary['aps']} APs, "
                f"{summary['stations']} stations, {summary['bt_devices']} BT devices"))
        elif not _state["connected"]:
            yield _sse_format("log", json.dumps(
                "[*] Ready — connect a device to start scanning"))
        yield _sse_format("result", json.dumps({"type": "all", "summary": summary}))
        try:
            while True:
                try:
                    event_type, data = q.get(timeout=15)
                    yield _sse_format(event_type, data)
                except queue.Empty:
                    # Keep-alive
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Reports page — serve actual report HTML files
# ---------------------------------------------------------------------------

@app.route("/reports/view/<filename>")
def reports_view(filename):
    if not filename.startswith("report_") or not filename.endswith(".html"):
        return "Not found", 404
    return send_from_directory(os.path.abspath(REPORTS_DIR), filename)


@app.route("/api/reports")
def api_reports_list():
    """Return list of saved reports."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    files = glob.glob(os.path.join(REPORTS_DIR, "report_*.html"))
    reports = []
    for f in sorted(files, reverse=True):
        name = os.path.basename(f)
        # Parse timestamp from filename: report_2025-01-15_143022.html
        ts_part = name.replace("report_", "").replace(".html", "")
        try:
            dt = datetime.strptime(ts_part, "%Y-%m-%d_%H%M%S")
            display = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            display = ts_part
        reports.append({"filename": name, "timestamp": display})
    return jsonify(reports)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def page_dashboard():
    auto_port = mr.find_serial_port() or ""
    # Build scan cards data for JS
    scan_cards_json = json.dumps([
        {"key": k, "name": v[0], "default_duration": v[3], "cmd": v[4]}
        for k, v in SCAN_TYPES.items()
    ])
    return _render_dashboard(auto_port, scan_cards_json)


@app.route("/reports")
def page_reports():
    return REPORTS_PAGE


# ---------------------------------------------------------------------------
# HTML Templates — inline
# ---------------------------------------------------------------------------

_CSS = """\
:root {
    --bg: #0a0a0a;
    --bg-card: #111111;
    --bg-btn: #1a1a1a;
    --bg-hover: #222222;
    --border: #333333;
    --text: #e0e0e0;
    --text-dim: #888888;
    --green: #00ff41;
    --amber: #ffaa00;
    --cyan: #00ccff;
    --red: #ff4444;
    --font: 'Courier New', monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: var(--bg); color: var(--text); font-family: var(--font);
    min-height: 100vh;
}
a { color: var(--cyan); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Nav */
.nav {
    background: #0d0d0d; border-bottom: 1px solid var(--border);
    padding: 12px 24px; display: flex; align-items: center; gap: 24px;
    position: sticky; top: 0; z-index: 100;
}
.nav-brand {
    color: var(--green); font-size: 1.2em; font-weight: bold;
    letter-spacing: 1px;
}
.nav a {
    color: var(--text-dim); padding: 6px 12px; border-radius: 4px;
    transition: all 0.2s;
}
.nav a:hover, .nav a.active {
    color: var(--green); background: var(--bg-btn); text-decoration: none;
}
.nav-right { margin-left: auto; }

/* Layout */
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }

/* Connection Panel */
.conn-panel {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px 20px; margin-bottom: 20px;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
.conn-panel label { color: var(--text-dim); font-size: 0.85em; }
.conn-panel input {
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    font-family: var(--font); padding: 8px 12px; border-radius: 4px;
    font-size: 0.9em;
}
.conn-panel input:focus { outline: none; border-color: var(--cyan); }
.conn-panel .port-input { width: 200px; }
.conn-panel .baud-input { width: 100px; }

.status-dot {
    width: 12px; height: 12px; border-radius: 50%; display: inline-block;
    margin-right: 6px; transition: background 0.3s;
}
.status-dot.off { background: var(--red); box-shadow: 0 0 6px var(--red); }
.status-dot.on { background: var(--green); box-shadow: 0 0 8px var(--green); }

/* Buttons */
.btn {
    background: var(--bg-btn); border: 1px solid var(--border); color: var(--text);
    font-family: var(--font); padding: 8px 16px; border-radius: 4px;
    cursor: pointer; font-size: 0.9em; transition: all 0.2s;
    display: inline-flex; align-items: center; gap: 6px;
}
.btn:hover { background: var(--bg-hover); border-color: #555; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-green { border-color: var(--green); color: var(--green); }
.btn-green:hover { background: rgba(0,255,65,0.1); }
.btn-red { border-color: var(--red); color: var(--red); }
.btn-red:hover { background: rgba(255,68,68,0.1); }
.btn-cyan { border-color: var(--cyan); color: var(--cyan); }
.btn-cyan:hover { background: rgba(0,204,255,0.1); }
.btn-amber { border-color: var(--amber); color: var(--amber); }
.btn-amber:hover { background: rgba(255,170,0,0.1); }

/* Scan Grid */
.scan-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px; margin-bottom: 20px;
}
.scan-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; transition: all 0.3s;
}
.scan-card.active {
    border-color: var(--green);
    box-shadow: 0 0 15px rgba(0,255,65,0.15), inset 0 0 15px rgba(0,255,65,0.03);
    animation: pulse-border 2s ease-in-out infinite;
}
@keyframes pulse-border {
    0%, 100% { box-shadow: 0 0 10px rgba(0,255,65,0.1); }
    50% { box-shadow: 0 0 20px rgba(0,255,65,0.25), inset 0 0 20px rgba(0,255,65,0.05); }
}
.scan-card-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 12px;
}
.scan-card-title { color: var(--green); font-size: 1em; font-weight: bold; }
.scan-badge {
    background: var(--bg); border: 1px solid var(--border); padding: 2px 10px;
    border-radius: 12px; font-size: 0.8em; color: var(--text-dim);
    min-width: 30px; text-align: center; transition: all 0.3s;
}
.scan-badge.has-data { color: var(--cyan); border-color: var(--cyan); }
.scan-card-controls {
    display: flex; align-items: center; gap: 8px;
}
.scan-card-controls input {
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    font-family: var(--font); padding: 6px 8px; border-radius: 4px;
    width: 60px; font-size: 0.85em; text-align: center;
}
.scan-card-controls input:focus { outline: none; border-color: var(--cyan); }
.scan-card-controls label { color: var(--text-dim); font-size: 0.8em; }
.scan-card-status {
    margin-top: 8px; font-size: 0.8em; color: var(--text-dim);
    min-height: 1.2em;
}

/* Action bar */
.action-bar {
    display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;
    align-items: center;
}
.action-bar .progress-text {
    color: var(--amber); font-size: 0.9em; margin-left: 8px;
}

/* Live feed */
.live-feed {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; margin-bottom: 20px;
}
.live-feed-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 10px;
}
.live-feed-header h3 { color: var(--green); font-size: 1em; }
.feed-log {
    background: var(--bg); border: 1px solid #1a1a1a; border-radius: 4px;
    padding: 12px; height: 250px; overflow-y: auto; font-size: 0.82em;
    line-height: 1.6;
}
.feed-log .log-line { white-space: pre-wrap; word-break: break-all; }
.feed-log .log-error { color: var(--red); }
.feed-log .log-success { color: var(--green); }
.feed-log .log-info { color: var(--cyan); }
.feed-log .log-warn { color: var(--amber); }

/* Reports page */
.reports-list {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden;
}
.report-row {
    display: flex; align-items: center; gap: 16px; padding: 12px 16px;
    border-bottom: 1px solid #1a1a1a; transition: background 0.2s;
}
.report-row:hover { background: var(--bg-btn); }
.report-row:last-child { border-bottom: none; }
.report-row .ts { color: var(--amber); min-width: 180px; }
.report-row .name { color: var(--text-dim); flex: 1; }
.report-row .actions { display: flex; gap: 8px; }

.report-viewer {
    margin-top: 20px; background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden;
}
.report-viewer iframe {
    width: 100%; height: 70vh; border: none; background: var(--bg);
}
.report-viewer-header {
    padding: 12px 16px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 12px;
}
.report-viewer-header h3 { color: var(--green); font-size: 0.95em; }

.empty-state {
    text-align: center; padding: 60px 20px; color: var(--text-dim);
}
.empty-state .icon { font-size: 2em; margin-bottom: 12px; color: var(--border); }
"""

_NAV_HTML = """\
<nav class="nav">
    <span class="nav-brand">// MARAUDER</span>
    <a href="/" id="nav-dashboard">Dashboard</a>
    <a href="/reports" id="nav-reports">Reports</a>
    <span class="nav-right" style="color:var(--text-dim);font-size:0.8em;">
        ESP32 Marauder Scan Dashboard
    </span>
</nav>
"""


def _render_dashboard(auto_port, scan_cards_json):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marauder Dashboard</title>
<style>
{_CSS}
</style>
</head>
<body>
{_NAV_HTML}
<div class="container">

<!-- Connection Panel -->
<div class="conn-panel">
    <div>
        <label>Serial Port</label><br>
        <input type="text" id="port-input" class="port-input"
               value="{auto_port}" placeholder="/dev/ttyUSB0 or auto">
    </div>
    <div>
        <label>Baud Rate</label><br>
        <input type="text" id="baud-input" class="baud-input" value="115200">
    </div>
    <button id="conn-btn" class="btn btn-green" onclick="toggleConnect()">Connect</button>
    <div style="display:flex;align-items:center;">
        <span id="status-dot" class="status-dot off"></span>
        <span id="status-text" style="color:var(--text-dim);font-size:0.85em;">Disconnected</span>
    </div>
</div>

<!-- Scan Cards -->
<div class="scan-grid" id="scan-grid"></div>

<!-- Action Bar -->
<div class="action-bar">
    <button id="run-all-btn" class="btn btn-cyan" onclick="runAllScans()" disabled>
        Run All Scans
    </button>
    <button id="stop-btn" class="btn btn-red" onclick="stopScan()" disabled>
        Stop Scan
    </button>
    <button id="report-btn" class="btn btn-amber" onclick="generateReport()">
        Generate Report
    </button>
    <button id="analyze-btn" class="btn" onclick="analyzeData()"
            style="background:#2a1a4a;border-color:#8b5cf6;color:#c4b5fd;">
        Analyze with AI
    </button>
    <span id="progress-text" class="progress-text"></span>
</div>

<!-- AI Analysis Panel (hidden until used) -->
<div id="analysis-panel" style="display:none;margin-bottom:20px;">
    <div style="background:var(--bg-card);border:1px solid #8b5cf6;border-radius:8px;padding:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <h3 style="color:#c4b5fd;font-size:1em;">// AI ANALYSIS</h3>
            <button class="btn" onclick="document.getElementById('analysis-panel').style.display='none'"
                    style="padding:4px 10px;font-size:0.8em;">Close</button>
        </div>
        <div id="analysis-content" style="color:var(--text);line-height:1.7;white-space:pre-wrap;font-size:0.9em;"></div>
    </div>
</div>

<!-- Live Feed -->
<div class="live-feed">
    <div class="live-feed-header">
        <h3>// LIVE FEED</h3>
        <button class="btn" onclick="clearFeed()" style="padding:4px 10px;font-size:0.8em;">
            Clear
        </button>
    </div>
    <div class="feed-log" id="feed-log"></div>
</div>

</div>

<script>
const SCAN_CARDS = {scan_cards_json};
let connected = false;
let scanning = false;
let evtSource = null;

// Build scan cards using DOM methods
function buildCards() {{
    const grid = document.getElementById('scan-grid');
    while (grid.firstChild) grid.removeChild(grid.firstChild);

    SCAN_CARDS.forEach(function(sc) {{
        const card = document.createElement('div');
        card.className = 'scan-card';
        card.id = 'card-' + sc.key;

        // Header
        const header = document.createElement('div');
        header.className = 'scan-card-header';
        const title = document.createElement('span');
        title.className = 'scan-card-title';
        title.textContent = sc.name;
        const badge = document.createElement('span');
        badge.className = 'scan-badge';
        badge.id = 'badge-' + sc.key;
        badge.textContent = '0';
        header.appendChild(title);
        header.appendChild(badge);

        // Controls
        const controls = document.createElement('div');
        controls.className = 'scan-card-controls';
        const durLabel = document.createElement('label');
        durLabel.textContent = 'Duration:';
        const durInput = document.createElement('input');
        durInput.type = 'number';
        durInput.id = 'dur-' + sc.key;
        durInput.value = sc.default_duration;
        durInput.min = '1';
        durInput.max = '300';
        const sLabel = document.createElement('label');
        sLabel.textContent = 's';
        const startBtn = document.createElement('button');
        startBtn.className = 'btn btn-green';
        startBtn.id = 'start-' + sc.key;
        startBtn.textContent = 'Start';
        startBtn.disabled = true;
        startBtn.setAttribute('data-scan-key', sc.key);
        startBtn.addEventListener('click', function() {{ startScan(sc.key); }});
        controls.appendChild(durLabel);
        controls.appendChild(durInput);
        controls.appendChild(sLabel);
        controls.appendChild(startBtn);

        // Status
        const status = document.createElement('div');
        status.className = 'scan-card-status';
        status.id = 'status-' + sc.key;

        card.appendChild(header);
        card.appendChild(controls);
        card.appendChild(status);
        grid.appendChild(card);
    }});
}}

// Connection
function toggleConnect() {{
    if (connected) {{
        fetch('/api/disconnect', {{method:'POST'}}).then(function(r){{return r.json();}}).then(function(d) {{
            setConnected(false);
        }});
    }} else {{
        const port = document.getElementById('port-input').value.trim() || 'auto';
        const baud = document.getElementById('baud-input').value.trim() || '115200';
        const btn = document.getElementById('conn-btn');
        btn.disabled = true;
        btn.textContent = 'Connecting...';
        fetch('/api/connect', {{
            method: 'POST',
            headers: {{'Content-Type':'application/json'}},
            body: JSON.stringify({{port: port, baud: parseInt(baud)}})
        }}).then(function(r){{return r.json();}}).then(function(d) {{
            if (d.ok) {{
                document.getElementById('port-input').value = d.port;
                setConnected(true);
            }} else {{
                addLog('[!] ' + (d.error||'Connection failed'), 'error');
                btn.disabled = false;
                btn.textContent = 'Connect';
            }}
        }}).catch(function(e) {{
            addLog('[!] Connection error: ' + e, 'error');
            btn.disabled = false;
            btn.textContent = 'Connect';
        }});
    }}
}}

function setConnected(state) {{
    connected = state;
    document.getElementById('status-dot').className = 'status-dot ' + (state?'on':'off');
    document.getElementById('status-text').textContent = state?'Connected':'Disconnected';
    const btn = document.getElementById('conn-btn');
    btn.textContent = state ? 'Disconnect' : 'Connect';
    btn.className = 'btn ' + (state ? 'btn-red' : 'btn-green');
    btn.disabled = false;
    document.getElementById('run-all-btn').disabled = !state;
    SCAN_CARDS.forEach(function(sc) {{
        document.getElementById('start-' + sc.key).disabled = !state;
    }});
    if (state) connectSSE();
}}

// SSE
function connectSSE() {{
    if (evtSource) evtSource.close();
    evtSource = new EventSource('/api/stream');

    evtSource.addEventListener('log', function(e) {{
        const msg = JSON.parse(e.data);
        let cls = '';
        if (msg.startsWith('[!]') || msg.startsWith('Error')) cls = 'error';
        else if (msg.startsWith('[+]')) cls = 'success';
        else if (msg.startsWith('[*]')) cls = 'info';
        else if (msg.startsWith('[>]')) cls = 'warn';
        addLog(msg, cls);
    }});

    evtSource.addEventListener('scan_start', function(e) {{
        const d = JSON.parse(e.data);
        const card = document.getElementById('card-' + d.type);
        if (card) card.classList.add('active');
        const st = document.getElementById('status-' + d.type);
        if (st) st.textContent = 'Scanning... (' + d.duration + 's)';
        scanning = true;
        document.getElementById('stop-btn').disabled = false;
        updateRunAllBtn();
    }});

    evtSource.addEventListener('scan_stop', function(e) {{
        const d = JSON.parse(e.data);
        const card = document.getElementById('card-' + d.type);
        if (card) card.classList.remove('active');
        const st = document.getElementById('status-' + d.type);
        if (st) st.textContent = '';
    }});

    evtSource.addEventListener('scan_complete', function(e) {{
        const d = JSON.parse(e.data);
        const st = document.getElementById('status-' + d.type);
        if (st) st.textContent = 'Complete';
        setTimeout(function() {{ if (st) st.textContent = ''; }}, 3000);
    }});

    evtSource.addEventListener('result', function(e) {{
        const d = JSON.parse(e.data);
        if (d.summary) updateBadges(d.summary);
    }});

    evtSource.addEventListener('error', function(e) {{
        try {{
            const d = JSON.parse(e.data);
            addLog('[!] ' + d.message, 'error');
        }} catch(ex) {{}}
    }});

    evtSource.addEventListener('status', function(e) {{
        const d = JSON.parse(e.data);
        if (d.summary) updateBadges(d.summary);
    }});

    evtSource.onerror = function(e) {{
        console.log('SSE error', e);
        addLog('[*] SSE reconnecting...', 'info');
    }};
}}

function updateBadges(summary) {{
    const map = {{
        aps: summary.aps || 0,
        stations: summary.stations || 0,
        probes: summary.probes || 0,
        bt: summary.bt_devices || 0,
        gps: summary.gps ? 'FIX' : '---',
        deauth: summary.deauths || 0,
        pmkid: summary.eapols || 0
    }};
    const keys = Object.keys(map);
    for (let i = 0; i < keys.length; i++) {{
        const k = keys[i];
        const v = map[k];
        const badge = document.getElementById('badge-' + k);
        if (badge) {{
            badge.textContent = v;
            badge.className = 'scan-badge' + ((v && v !== '---' && v !== 0) ? ' has-data' : '');
        }}
    }}
}}

function updateRunAllBtn() {{
    document.getElementById('run-all-btn').disabled = !connected || scanning;
    SCAN_CARDS.forEach(function(sc) {{
        document.getElementById('start-' + sc.key).disabled = !connected || scanning;
    }});
}}

// Scans
function startScan(key) {{
    const dur = parseInt(document.getElementById('dur-' + key).value) || 15;
    fetch('/api/scan/start', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify({{type: key, duration: dur}})
    }}).then(function(r){{return r.json();}}).then(function(d) {{
        if (!d.ok) addLog('[!] ' + d.error, 'error');
    }});
}}

function stopScan() {{
    fetch('/api/scan/stop', {{method:'POST'}}).then(function(r){{return r.json();}}).then(function(d) {{
        document.getElementById('stop-btn').disabled = true;
        scanning = false;
        updateRunAllBtn();
        // Clear all active states
        SCAN_CARDS.forEach(function(sc) {{
            document.getElementById('card-' + sc.key).classList.remove('active');
            document.getElementById('status-' + sc.key).textContent = '';
        }});
        document.getElementById('progress-text').textContent = '';
    }});
}}

function runAllScans() {{
    const durations = {{}};
    SCAN_CARDS.forEach(function(sc) {{
        durations[sc.key] = parseInt(document.getElementById('dur-' + sc.key).value) || sc.default_duration;
    }});
    scanning = true;
    updateRunAllBtn();
    fetch('/api/scan/all', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify({{durations: durations}})
    }}).then(function(r){{return r.json();}}).then(function(d) {{
        if (!d.ok) {{
            addLog('[!] ' + d.error, 'error');
            scanning = false;
            updateRunAllBtn();
        }}
    }});
}}

function generateReport() {{
    fetch('/api/report/generate', {{method:'POST'}}).then(function(r){{return r.json();}}).then(function(d) {{
        if (d.ok) {{
            addLog('[+] Report generated: ' + d.html, 'success');
        }} else {{
            addLog('[!] Report error: ' + (d.error||'unknown'), 'error');
        }}
    }});
}}

function analyzeData() {{
    var btn = document.getElementById('analyze-btn');
    btn.disabled = true;
    btn.textContent = 'Analyzing...';
    addLog('[*] Sending data to Ollama for AI analysis...', 'info');

    fetch('/api/analyze', {{method:'POST'}}).then(function(r){{return r.json();}}).then(function(d) {{
        btn.disabled = false;
        btn.textContent = 'Analyze with AI';
        if (d.ok) {{
            var panel = document.getElementById('analysis-panel');
            var content = document.getElementById('analysis-content');
            content.textContent = d.analysis;
            panel.style.display = 'block';
            panel.scrollIntoView({{behavior: 'smooth'}});
            addLog('[+] AI analysis complete — see panel above', 'success');
        }} else {{
            addLog('[!] Analysis failed: ' + (d.error||'unknown'), 'error');
        }}
    }}).catch(function(e) {{
        btn.disabled = false;
        btn.textContent = 'Analyze with AI';
        addLog('[!] Analysis error: ' + e, 'error');
    }});
}}

// Live feed
function addLog(text, cls) {{
    const log = document.getElementById('feed-log');
    const line = document.createElement('div');
    line.className = 'log-line' + (cls ? ' log-' + cls : '');
    const ts = new Date().toLocaleTimeString();
    line.textContent = ts + '  ' + text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
    // Keep max 500 lines
    while (log.children.length > 500) log.removeChild(log.firstChild);
}}

function clearFeed() {{
    const log = document.getElementById('feed-log');
    while (log.firstChild) log.removeChild(log.firstChild);
}}

// Poll status periodically to keep UI in sync
setInterval(function() {{
    fetch('/api/status').then(function(r){{return r.json();}}).then(function(d) {{
        if (d.scanning !== scanning) {{
            scanning = d.scanning;
            updateRunAllBtn();
            document.getElementById('stop-btn').disabled = !scanning;
            if (!scanning) {{
                SCAN_CARDS.forEach(function(sc) {{
                    document.getElementById('card-' + sc.key).classList.remove('active');
                    document.getElementById('status-' + sc.key).textContent = '';
                }});
                document.getElementById('progress-text').textContent = '';
            }}
        }}
        if (d.run_all_progress) {{
            document.getElementById('progress-text').textContent = d.run_all_progress;
        }} else {{
            document.getElementById('progress-text').textContent = '';
        }}
        if (d.results_summary) updateBadges(d.results_summary);
    }}).catch(function(){{}});
}}, 3000);

// Init
buildCards();
document.getElementById('nav-dashboard').classList.add('active');

// Always connect SSE on load for live feed
connectSSE();
addLog('[*] Dashboard loaded — waiting for events...', 'info');

// Check initial status and populate badges
fetch('/api/status').then(function(r){{return r.json();}}).then(function(d) {{
    if (d.connected) setConnected(true);
    if (d.results_summary) {{
        updateBadges(d.results_summary);
        var s = d.results_summary;
        if (s.aps || s.bt_devices || s.stations) {{
            addLog('[+] Data loaded: ' + s.aps + ' APs, ' + s.stations + ' stations, ' + s.bt_devices + ' BT devices', 'success');
        }}
    }}
}});
</script>
</body>
</html>"""


REPORTS_PAGE = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marauder Reports</title>
<style>
{_CSS}
</style>
</head>
<body>
{_NAV_HTML}
<div class="container">

<h2 style="color:var(--green);margin-bottom:16px;">// SAVED REPORTS</h2>

<div class="reports-list" id="reports-list">
    <div class="empty-state" id="empty-state">
        <div class="icon">[  ]</div>
        <div>No reports yet. Run scans and generate a report from the dashboard.</div>
    </div>
</div>

<div class="report-viewer" id="report-viewer" style="display:none;">
    <div class="report-viewer-header">
        <h3 id="viewer-title">Report</h3>
        <button class="btn" onclick="closeViewer()" style="padding:4px 10px;font-size:0.8em;">
            Close
        </button>
    </div>
    <iframe id="viewer-frame" src="about:blank"></iframe>
</div>

</div>

<script>
function loadReports() {{
    fetch('/api/reports').then(function(r){{return r.json();}}).then(function(reports) {{
        const list = document.getElementById('reports-list');
        const empty = document.getElementById('empty-state');

        // Remove existing rows
        var rows = list.querySelectorAll('.report-row');
        for (var i = 0; i < rows.length; i++) rows[i].remove();

        if (reports.length === 0) {{
            empty.style.display = 'block';
            return;
        }}
        empty.style.display = 'none';

        reports.forEach(function(rpt) {{
            var row = document.createElement('div');
            row.className = 'report-row';

            var tsSpan = document.createElement('span');
            tsSpan.className = 'ts';
            tsSpan.textContent = rpt.timestamp;

            var nameSpan = document.createElement('span');
            nameSpan.className = 'name';
            nameSpan.textContent = rpt.filename;

            var actionsSpan = document.createElement('span');
            actionsSpan.className = 'actions';

            var viewBtn = document.createElement('button');
            viewBtn.className = 'btn btn-cyan';
            viewBtn.style.cssText = 'padding:4px 10px;font-size:0.8em;';
            viewBtn.textContent = 'View';
            viewBtn.setAttribute('data-filename', rpt.filename);
            viewBtn.addEventListener('click', function() {{ viewReport(this.getAttribute('data-filename')); }});

            var delBtn = document.createElement('button');
            delBtn.className = 'btn btn-red';
            delBtn.style.cssText = 'padding:4px 10px;font-size:0.8em;';
            delBtn.textContent = 'Delete';
            delBtn.setAttribute('data-filename', rpt.filename);
            delBtn.addEventListener('click', function() {{ deleteReport(this.getAttribute('data-filename')); }});

            actionsSpan.appendChild(viewBtn);
            actionsSpan.appendChild(delBtn);
            row.appendChild(tsSpan);
            row.appendChild(nameSpan);
            row.appendChild(actionsSpan);
            list.appendChild(row);
        }});
    }});
}}

function viewReport(filename) {{
    document.getElementById('report-viewer').style.display = 'block';
    document.getElementById('viewer-title').textContent = filename;
    document.getElementById('viewer-frame').src = '/reports/view/' + encodeURIComponent(filename);
    document.getElementById('report-viewer').scrollIntoView({{behavior: 'smooth'}});
}}

function closeViewer() {{
    document.getElementById('report-viewer').style.display = 'none';
    document.getElementById('viewer-frame').src = 'about:blank';
}}

function deleteReport(filename) {{
    if (!confirm('Delete ' + filename + '?')) return;
    fetch('/api/report/' + encodeURIComponent(filename), {{method:'DELETE'}}).then(function(r){{return r.json();}}).then(function(d) {{
        if (d.ok) loadReports();
    }});
}}

document.getElementById('nav-reports').classList.add('active');
loadReports();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Marauder Web Dashboard — Flask UI for ESP32 Marauder scans")
    parser.add_argument("--host", default="127.0.0.1", help="Web server bind address")
    parser.add_argument("--port", type=int, default=5000, help="Web server port")
    parser.add_argument("--reports-dir", default="./reports", help="Directory for saved reports")
    parser.add_argument("--demo", action="store_true", help="Start with mock data loaded")
    args = parser.parse_args()

    global REPORTS_DIR
    REPORTS_DIR = os.path.abspath(args.reports_dir)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    if args.demo:
        print("[*] Demo mode — loading mock scan data")
        with _results_lock:
            _state["results"] = mr.demo_results()

    print(f"[*] Starting Marauder Dashboard on http://{args.host}:{args.port}")
    print(f"[*] Reports directory: {REPORTS_DIR}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
