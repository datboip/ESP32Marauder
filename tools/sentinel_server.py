#!/usr/bin/env python3
"""Sentinel Server — Flask API for ESP32 Marauder autonomous wardrive fleet.

Devices running Sentinel mode periodically phone home to this server to:
- Send heartbeats with status (battery, GPS, heap, scan mode, uptime)
- Upload wardrive CSV logs and GPX POI files
- Pull per-device config and pending commands
- Acknowledge command execution

All endpoints require an X-API-Key header. Keys are configured via the
API_KEYS env var (comma-separated), defaulting to "changeme".
"""

import os
import sqlite3
from datetime import datetime

from flask import Flask, g, jsonify, redirect, request

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "sentinel.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")
API_KEYS = set(
    k.strip()
    for k in os.environ.get("API_KEYS", "changeme").split(",")
    if k.strip()
)
PORT = int(os.environ.get("PORT", "5001"))

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "sentinel_schema.sql")

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_db():
    """Return per-request database connection stored on Flask g."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables from the schema file if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.close()


def ensure_device(device_id):
    """Auto-create device and config rows on first contact."""
    db = get_db()
    row = db.execute("SELECT 1 FROM devices WHERE device_id = ?",
                     (device_id,)).fetchone()
    if row is None:
        db.execute("INSERT INTO devices (device_id) VALUES (?)",
                   (device_id,))
        db.execute("INSERT INTO config (device_id) VALUES (?)",
                   (device_id,))
        db.commit()


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


@app.before_request
def check_api_key():
    if request.path == "/" or request.path.startswith("/dashboard"):
        return None
    key = request.headers.get("X-API-Key", "")
    if key not in API_KEYS:
        return jsonify({"error": "unauthorized"}), 401


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    """Receive device heartbeat and upsert device record."""
    data = request.get_json(force=True)
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    ensure_device(device_id)
    db = get_db()
    db.execute(
        """UPDATE devices SET
               device_name = ?,
               last_heartbeat = ?,
               battery_pct = ?,
               scan_mode = ?,
               free_heap = ?,
               lat = ?,
               lon = ?,
               uptime_sec = ?
           WHERE device_id = ?""",
        (
            data.get("device_name", ""),
            datetime.utcnow().isoformat(),
            data.get("battery_pct"),
            data.get("scan_mode", "wardrive"),
            data.get("free_heap"),
            data.get("lat"),
            data.get("lon"),
            data.get("uptime_sec"),
            device_id,
        ),
    )
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/upload", methods=["POST"])
def upload():
    """Receive a raw file body and save to disk."""
    device_id = request.headers.get("X-Device-Id", "")
    filename = request.headers.get("X-Filename", "")
    if not device_id or not filename:
        return jsonify({"error": "X-Device-Id and X-Filename required"}), 400

    ensure_device(device_id)

    safe_id = device_id.replace(":", "")
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    dest_dir = os.path.join(UPLOAD_DIR, safe_id)
    os.makedirs(dest_dir, exist_ok=True)

    dest_name = f"{ts}_{filename}"
    dest_path = os.path.join(dest_dir, dest_name)

    body = request.get_data()
    with open(dest_path, "wb") as f:
        f.write(body)

    db = get_db()
    db.execute(
        "INSERT INTO uploads (device_id, filename, size_bytes, filepath) "
        "VALUES (?, ?, ?, ?)",
        (device_id, filename, len(body), dest_path),
    )
    db.commit()
    return jsonify({"status": "ok", "filepath": dest_path, "size": len(body)})


@app.route("/api/config/<device_id>", methods=["GET"])
def get_config(device_id):
    """Return config JSON for a device."""
    ensure_device(device_id)
    db = get_db()
    row = db.execute("SELECT * FROM config WHERE device_id = ?",
                     (device_id,)).fetchone()
    return jsonify(dict(row))


@app.route("/api/config/<device_id>", methods=["PUT"])
def put_config(device_id):
    """Update config fields for a device."""
    ensure_device(device_id)
    data = request.get_json(force=True)
    allowed = {"scan_mode", "phone_home_interval_min",
               "dead_man_timeout_hrs", "active"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "no valid fields"}), 400

    db = get_db()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [device_id]
    db.execute(f"UPDATE config SET {set_clause} WHERE device_id = ?", vals)
    db.commit()
    return jsonify({"status": "ok", "updated": list(updates.keys())})


@app.route("/api/commands/<device_id>", methods=["GET"])
def get_commands(device_id):
    """Return pending commands for a device, then mark them dispatched."""
    ensure_device(device_id)
    db = get_db()
    rows = db.execute(
        "SELECT id, cmd, args, status, created_at FROM commands "
        "WHERE device_id = ? AND status = 'pending'",
        (device_id,),
    ).fetchall()
    cmds = [dict(r) for r in rows]

    if cmds:
        ids = [c["id"] for c in cmds]
        placeholders = ",".join("?" * len(ids))
        db.execute(
            f"UPDATE commands SET status = 'dispatched' "
            f"WHERE id IN ({placeholders})",
            ids,
        )
        db.commit()

    return jsonify(cmds)


@app.route("/api/commands/<device_id>", methods=["POST"])
def post_command(device_id):
    """Create a new command for a device (admin use)."""
    ensure_device(device_id)
    data = request.get_json(force=True)
    cmd = data.get("cmd")
    if not cmd:
        return jsonify({"error": "cmd required"}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO commands (device_id, cmd, args) VALUES (?, ?, ?)",
        (device_id, cmd, data.get("args", "")),
    )
    db.commit()
    return jsonify({"status": "ok", "id": cur.lastrowid}), 201


@app.route("/api/commands/<device_id>/history", methods=["GET"])
def command_history(device_id):
    """Return all commands for a device without marking them dispatched."""
    ensure_device(device_id)
    db = get_db()
    rows = db.execute(
        "SELECT id, cmd, args, status, created_at, acked_at FROM commands "
        "WHERE device_id = ? ORDER BY created_at DESC",
        (device_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/ack", methods=["POST"])
def ack():
    """Acknowledge command execution."""
    data = request.get_json(force=True)
    cmd_id = data.get("id")
    if cmd_id is None:
        return jsonify({"error": "id required"}), 400

    db = get_db()
    db.execute(
        "UPDATE commands SET status = 'acked', acked_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), cmd_id),
    )
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/devices", methods=["GET"])
def list_devices():
    """List all registered devices."""
    db = get_db()
    rows = db.execute("SELECT * FROM devices").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/uploads/<device_id>", methods=["GET"])
def list_uploads(device_id):
    """List uploads for a specific device."""
    ensure_device(device_id)
    db = get_db()
    rows = db.execute(
        "SELECT id, filename, size_bytes, uploaded_at, filepath "
        "FROM uploads WHERE device_id = ? ORDER BY uploaded_at DESC",
        (device_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sentinel Fleet Dashboard</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e; color: #e0e0e0; min-height: 100vh;
}
.mono { font-family: 'Courier New', Courier, monospace; }
a { color: #00d4ff; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Top bar */
.topbar {
    background: #0f0f23; padding: 12px 24px; display: flex;
    align-items: center; justify-content: space-between;
    border-bottom: 1px solid #00d4ff33;
}
.topbar h1 { font-size: 1.3rem; color: #00d4ff; }
.topbar .right { display: flex; align-items: center; gap: 12px; }
.topbar button {
    background: #16213e; color: #e0e0e0; border: 1px solid #00d4ff55;
    padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: .85rem;
}
.topbar button:hover { background: #1a2a4e; }
.topbar .status-dot {
    width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}

/* Login overlay */
#login-overlay {
    position: fixed; inset: 0; background: #1a1a2eee;
    display: flex; align-items: center; justify-content: center; z-index: 100;
}
#login-box {
    background: #16213e; padding: 32px; border-radius: 8px;
    border: 1px solid #00d4ff44; text-align: center; min-width: 320px;
}
#login-box h2 { color: #00d4ff; margin-bottom: 16px; }
#login-box input {
    width: 100%; padding: 10px; background: #0f0f23; border: 1px solid #00d4ff55;
    color: #e0e0e0; border-radius: 4px; font-size: 1rem; margin-bottom: 12px;
}
#login-box button {
    background: #00d4ff; color: #0f0f23; border: none; padding: 10px 24px;
    border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 1rem;
}
#login-box .error { color: #ff4466; font-size: .85rem; margin-top: 8px; }

/* Main content */
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }
.fleet-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px;
}
.fleet-header h2 { font-size: 1.1rem; color: #aaa; }
.fleet-header .count { color: #00ff88; }

/* Device grid */
.device-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 16px; margin-bottom: 24px;
}
.device-card {
    background: #16213e; border-radius: 8px; padding: 16px;
    border: 1px solid transparent; cursor: pointer; transition: border-color .2s;
}
.device-card:hover { border-color: #00d4ff55; }
.device-card.selected { border-color: #00d4ff; }
.card-top { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.card-top .status-dot {
    width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
}
.card-top .name { font-weight: 600; font-size: 1rem; }
.card-top .id { color: #888; font-size: .75rem; }
.card-stats {
    display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; font-size: .85rem;
}
.card-stats .label { color: #888; }
.card-stats .val { color: #e0e0e0; }
.dot-green { background: #00ff88; }
.dot-yellow { background: #ffcc00; }
.dot-red { background: #ff4466; }
.dot-gray { background: #555; }

/* Detail panel */
#detail-panel {
    background: #16213e; border-radius: 8px; padding: 20px;
    border: 1px solid #00d4ff33; display: none;
}
#detail-panel.visible { display: block; }
.detail-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px;
}
.detail-header h2 { color: #00d4ff; font-size: 1.1rem; }
.detail-header button {
    background: none; border: none; color: #888; cursor: pointer;
    font-size: 1.2rem;
}
.detail-tabs { display: flex; gap: 0; margin-bottom: 16px; }
.detail-tabs button {
    background: #0f0f23; color: #aaa; border: 1px solid #00d4ff22;
    padding: 8px 18px; cursor: pointer; font-size: .85rem;
}
.detail-tabs button:first-child { border-radius: 4px 0 0 4px; }
.detail-tabs button:last-child { border-radius: 0 4px 4px 0; }
.detail-tabs button.active { background: #00d4ff22; color: #00d4ff; border-color: #00d4ff55; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Config form */
.config-form { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; max-width: 500px; }
.config-form label { color: #aaa; font-size: .85rem; display: flex; flex-direction: column; gap: 4px; }
.config-form select, .config-form input {
    background: #0f0f23; border: 1px solid #00d4ff44; color: #e0e0e0;
    padding: 8px; border-radius: 4px; font-size: .9rem;
}
.config-form .full { grid-column: 1 / -1; }
.btn-primary {
    background: #00d4ff; color: #0f0f23; border: none; padding: 8px 20px;
    border-radius: 4px; cursor: pointer; font-weight: 600;
}
.btn-primary:hover { background: #00bfe0; }
.btn-danger {
    background: #ff4466; color: #fff; border: none; padding: 8px 20px;
    border-radius: 4px; cursor: pointer; font-weight: 600;
}

/* Command form */
.cmd-form { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 16px; }
.cmd-form label { color: #aaa; font-size: .85rem; display: flex; flex-direction: column; gap: 4px; }
.cmd-form select, .cmd-form input {
    background: #0f0f23; border: 1px solid #00d4ff44; color: #e0e0e0;
    padding: 8px; border-radius: 4px; font-size: .9rem;
}

/* Tables */
.data-table { width: 100%; border-collapse: collapse; font-size: .85rem; margin-top: 8px; }
.data-table th {
    text-align: left; color: #888; padding: 8px; border-bottom: 1px solid #00d4ff22;
}
.data-table td { padding: 8px; border-bottom: 1px solid #ffffff08; }
.data-table tr:hover { background: #ffffff05; }
.badge {
    padding: 2px 8px; border-radius: 10px; font-size: .75rem; font-weight: 600;
}
.badge-pending { background: #ffcc0033; color: #ffcc00; }
.badge-dispatched { background: #00d4ff22; color: #00d4ff; }
.badge-acked { background: #00ff8822; color: #00ff88; }
.toast {
    position: fixed; bottom: 20px; right: 20px; background: #00ff88;
    color: #0f0f23; padding: 10px 20px; border-radius: 6px; font-weight: 600;
    display: none; z-index: 200;
}
.toast.error { background: #ff4466; color: #fff; }
.toast.visible { display: block; }

@media (max-width: 600px) {
    .device-grid { grid-template-columns: 1fr; }
    .config-form { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="topbar">
    <h1>Sentinel Fleet Dashboard</h1>
    <div class="right">
        <span id="refresh-status" style="font-size:.8rem;color:#888;">--</span>
        <button onclick="loadDevices()">Refresh</button>
        <button id="logout-btn" onclick="logout()">Logout</button>
    </div>
</div>

<div id="login-overlay">
    <div id="login-box">
        <h2>Sentinel API</h2>
        <p style="color:#888;margin-bottom:16px;font-size:.9rem;">Enter your API key to access the fleet dashboard.</p>
        <input type="password" id="api-key-input" placeholder="API Key" autocomplete="off">
        <button onclick="doLogin()">Connect</button>
        <div id="login-error" class="error"></div>
    </div>
</div>

<div class="container" id="main-content" style="display:none;">
    <div class="fleet-header">
        <h2>Fleet Devices <span id="device-count" class="count"></span></h2>
    </div>
    <div class="device-grid" id="device-grid"></div>

    <div id="detail-panel">
        <div class="detail-header">
            <h2 id="detail-title">Device Detail</h2>
            <button onclick="closeDetail()">&times;</button>
        </div>
        <div class="detail-tabs">
            <button class="active" onclick="switchTab(this,'tab-info')">Info</button>
            <button onclick="switchTab(this,'tab-config')">Config</button>
            <button onclick="switchTab(this,'tab-commands')">Commands</button>
            <button onclick="switchTab(this,'tab-uploads')">Uploads</button>
        </div>

        <div id="tab-info" class="tab-content active">
            <div class="card-stats" id="detail-info" style="max-width:500px;"></div>
        </div>

        <div id="tab-config" class="tab-content">
            <div class="config-form" id="config-form">
                <label>Scan Mode
                    <select id="cfg-scan-mode">
                        <option>wardrive</option><option>probe</option>
                        <option>deauth</option><option>beacon</option>
                        <option>sniff</option><option>bt_scan</option>
                    </select>
                </label>
                <label>Phone Home Interval (min)
                    <input type="number" id="cfg-interval" min="1" max="1440" value="5">
                </label>
                <label>Dead Man Timeout (hrs)
                    <input type="number" id="cfg-deadman" min="1" max="168" value="24">
                </label>
                <label>Active
                    <select id="cfg-active"><option value="1">Yes</option><option value="0">No</option></select>
                </label>
                <div class="full">
                    <button class="btn-primary" onclick="saveConfig()">Save Config</button>
                </div>
            </div>
        </div>

        <div id="tab-commands" class="tab-content">
            <div class="cmd-form">
                <label>Command
                    <select id="cmd-select">
                        <option value="reboot">reboot</option>
                        <option value="switch_mode">switch_mode</option>
                        <option value="clear_sd">clear_sd</option>
                        <option value="wipe">wipe</option>
                    </select>
                </label>
                <label>Args
                    <input type="text" id="cmd-args" placeholder="optional args">
                </label>
                <button class="btn-primary" style="margin-bottom:0;align-self:flex-end;" onclick="sendCommand()">Send Command</button>
            </div>
            <h3 style="color:#aaa;font-size:.9rem;margin-bottom:4px;">Command History</h3>
            <table class="data-table" id="cmd-history-table">
                <thead><tr><th>ID</th><th>Command</th><th>Args</th><th>Status</th><th>Created</th><th>Acked</th></tr></thead>
                <tbody></tbody>
            </table>
        </div>

        <div id="tab-uploads" class="tab-content">
            <table class="data-table" id="upload-table">
                <thead><tr><th>Filename</th><th>Size</th><th>Uploaded</th></tr></thead>
                <tbody></tbody>
            </table>
        </div>
    </div>
</div>

<div id="toast" class="toast"></div>

<script>
let apiKey = sessionStorage.getItem('sentinel_api_key') || '';
let devices = [];
let selectedDeviceId = null;
let refreshTimer = null;

function getHeaders() {
    return { 'X-API-Key': apiKey, 'Content-Type': 'application/json' };
}

function showToast(msg, isError) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast visible' + (isError ? ' error' : '');
    setTimeout(function() { t.className = 'toast'; }, 3000);
}

function esc(str) {
    if (str == null) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

function timeAgo(isoStr) {
    if (!isoStr) return 'never';
    const diff = (Date.now() - new Date(isoStr + 'Z').getTime()) / 1000;
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function statusClass(isoStr) {
    if (!isoStr) return 'dot-gray';
    const diff = (Date.now() - new Date(isoStr + 'Z').getTime()) / 1000;
    if (diff < 300) return 'dot-green';
    if (diff < 1800) return 'dot-yellow';
    return 'dot-red';
}

function formatBytes(b) {
    if (b == null) return '--';
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1048576).toFixed(1) + ' MB';
}

function formatUptime(sec) {
    if (sec == null) return '--';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return h + 'h ' + m + 'm';
}

// Login / Logout
function checkAuth() {
    if (apiKey) {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('main-content').style.display = 'block';
        loadDevices();
        startAutoRefresh();
    }
}

async function doLogin() {
    const input = document.getElementById('api-key-input');
    const key = input.value.trim();
    if (!key) return;
    try {
        const resp = await fetch('/api/devices', { headers: { 'X-API-Key': key } });
        if (!resp.ok) throw new Error('Invalid API key');
        apiKey = key;
        sessionStorage.setItem('sentinel_api_key', key);
        checkAuth();
    } catch (e) {
        document.getElementById('login-error').textContent = e.message;
    }
}

document.getElementById('api-key-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') doLogin();
});

function logout() {
    apiKey = '';
    sessionStorage.removeItem('sentinel_api_key');
    if (refreshTimer) clearInterval(refreshTimer);
    document.getElementById('login-overlay').style.display = 'flex';
    document.getElementById('main-content').style.display = 'none';
    document.getElementById('device-grid').textContent = '';
    closeDetail();
}

// Auto-refresh
function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(loadDevices, 15000);
}

// Load devices
async function loadDevices() {
    try {
        const resp = await fetch('/api/devices', { headers: getHeaders() });
        if (!resp.ok) { if (resp.status === 401) logout(); return; }
        devices = await resp.json();
        renderDevices();
        document.getElementById('refresh-status').textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
        console.error('Failed to load devices', e);
    }
}

function renderDevices() {
    const grid = document.getElementById('device-grid');
    document.getElementById('device-count').textContent = '(' + devices.length + ')';
    grid.textContent = '';
    devices.forEach(function(d) {
        const dot = statusClass(d.last_heartbeat);
        const ago = timeAgo(d.last_heartbeat);
        const card = document.createElement('div');
        card.className = 'device-card' + (d.device_id === selectedDeviceId ? ' selected' : '');
        card.addEventListener('click', function() { selectDevice(d.device_id); });

        const top = document.createElement('div');
        top.className = 'card-top';
        const dotSpan = document.createElement('span');
        dotSpan.className = 'status-dot ' + dot;
        const nameSpan = document.createElement('span');
        nameSpan.className = 'name';
        nameSpan.textContent = d.device_name || 'Unnamed';
        const idSpan = document.createElement('span');
        idSpan.className = 'id mono';
        idSpan.textContent = d.device_id;
        top.appendChild(dotSpan);
        top.appendChild(nameSpan);
        top.appendChild(idSpan);

        const stats = document.createElement('div');
        stats.className = 'card-stats';
        var pairs = [
            ['Heartbeat', ago],
            ['Battery', d.battery_pct != null ? d.battery_pct + '%' : '--'],
            ['Mode', d.scan_mode || '--'],
            ['Heap', formatBytes(d.free_heap)],
            ['Uptime', formatUptime(d.uptime_sec)],
            ['GPS', d.lat != null ? Number(d.lat).toFixed(4) + ', ' + Number(d.lon).toFixed(4) : '--']
        ];
        pairs.forEach(function(p) {
            var lbl = document.createElement('span');
            lbl.className = 'label';
            lbl.textContent = p[0];
            var val = document.createElement('span');
            val.className = 'val' + (p[0] === 'GPS' ? ' mono' : '');
            val.textContent = p[1];
            stats.appendChild(lbl);
            stats.appendChild(val);
        });

        card.appendChild(top);
        card.appendChild(stats);
        grid.appendChild(card);
    });
}

// Device detail
async function selectDevice(deviceId) {
    selectedDeviceId = deviceId;
    renderDevices();
    const panel = document.getElementById('detail-panel');
    panel.classList.add('visible');
    const d = devices.find(function(x) { return x.device_id === deviceId; });
    document.getElementById('detail-title').textContent =
        (d && d.device_name ? d.device_name : 'Device') + ' \\u2014 ' + deviceId;

    // Info tab
    if (d) {
        const info = document.getElementById('detail-info');
        info.textContent = '';
        var infoPairs = [
            ['Device ID', d.device_id, true],
            ['Name', d.device_name || '--', false],
            ['Last Heartbeat', timeAgo(d.last_heartbeat) + ' (' + (d.last_heartbeat || 'never') + ')', false],
            ['Battery', d.battery_pct != null ? d.battery_pct + '%' : '--', false],
            ['Scan Mode', d.scan_mode || '--', false],
            ['Free Heap', formatBytes(d.free_heap), false],
            ['Uptime', formatUptime(d.uptime_sec), false],
            ['GPS', d.lat != null ? d.lat + ', ' + d.lon : '--', true]
        ];
        infoPairs.forEach(function(p) {
            var lbl = document.createElement('span');
            lbl.className = 'label';
            lbl.textContent = p[0];
            var val = document.createElement('span');
            val.className = 'val' + (p[2] ? ' mono' : '');
            val.textContent = p[1];
            info.appendChild(lbl);
            info.appendChild(val);
        });
    }

    // Load config
    try {
        const resp = await fetch('/api/config/' + encodeURIComponent(deviceId), { headers: getHeaders() });
        if (resp.ok) {
            const cfg = await resp.json();
            document.getElementById('cfg-scan-mode').value = cfg.scan_mode || 'wardrive';
            document.getElementById('cfg-interval').value = cfg.phone_home_interval_min || 5;
            document.getElementById('cfg-deadman').value = cfg.dead_man_timeout_hrs || 24;
            document.getElementById('cfg-active').value = cfg.active != null ? cfg.active : 1;
        }
    } catch (e) { console.error(e); }

    loadCommandHistory();
    loadUploads();

    // Reset tabs to Info
    switchTab(document.querySelector('.detail-tabs button'), 'tab-info');
}

function closeDetail() {
    selectedDeviceId = null;
    document.getElementById('detail-panel').classList.remove('visible');
    renderDevices();
}

function switchTab(btn, tabId) {
    document.querySelectorAll('.detail-tabs button').forEach(function(b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-content').forEach(function(t) { t.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById(tabId).classList.add('active');
}

// Config
async function saveConfig() {
    if (!selectedDeviceId) return;
    const body = {
        scan_mode: document.getElementById('cfg-scan-mode').value,
        phone_home_interval_min: parseInt(document.getElementById('cfg-interval').value),
        dead_man_timeout_hrs: parseInt(document.getElementById('cfg-deadman').value),
        active: parseInt(document.getElementById('cfg-active').value)
    };
    try {
        const resp = await fetch('/api/config/' + encodeURIComponent(selectedDeviceId), {
            method: 'PUT', headers: getHeaders(), body: JSON.stringify(body)
        });
        if (resp.ok) showToast('Config saved');
        else showToast('Failed to save config', true);
    } catch (e) { showToast('Error: ' + e.message, true); }
}

// Commands
async function sendCommand() {
    if (!selectedDeviceId) return;
    const cmd = document.getElementById('cmd-select').value;
    const args = document.getElementById('cmd-args').value;
    try {
        const resp = await fetch('/api/commands/' + encodeURIComponent(selectedDeviceId), {
            method: 'POST', headers: getHeaders(),
            body: JSON.stringify({ cmd: cmd, args: args })
        });
        if (resp.ok) {
            showToast('Command sent: ' + cmd);
            document.getElementById('cmd-args').value = '';
            loadCommandHistory();
        } else showToast('Failed to send command', true);
    } catch (e) { showToast('Error: ' + e.message, true); }
}

async function loadCommandHistory() {
    if (!selectedDeviceId) return;
    try {
        const resp = await fetch('/api/commands/' + encodeURIComponent(selectedDeviceId) + '/history', { headers: getHeaders() });
        if (!resp.ok) return;
        const cmds = await resp.json();
        const tbody = document.querySelector('#cmd-history-table tbody');
        tbody.textContent = '';
        cmds.forEach(function(c) {
            const tr = document.createElement('tr');
            var cells = [
                [String(c.id), false],
                [c.cmd, true],
                [c.args || '--', false],
                [null, false],
                [c.created_at || '--', false],
                [c.acked_at || '--', false]
            ];
            cells.forEach(function(cell, i) {
                var td = document.createElement('td');
                if (i === 1) td.className = 'mono';
                if (i === 3) {
                    var badge = document.createElement('span');
                    badge.className = 'badge badge-' + c.status;
                    badge.textContent = c.status;
                    td.appendChild(badge);
                } else {
                    td.textContent = cell[0];
                    if (cell[1]) td.className = 'mono';
                }
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    } catch (e) { console.error(e); }
}

// Uploads
async function loadUploads() {
    if (!selectedDeviceId) return;
    try {
        const resp = await fetch('/api/uploads/' + encodeURIComponent(selectedDeviceId), { headers: getHeaders() });
        if (!resp.ok) return;
        const uploads = await resp.json();
        const tbody = document.querySelector('#upload-table tbody');
        tbody.textContent = '';
        uploads.forEach(function(u) {
            const tr = document.createElement('tr');
            var td1 = document.createElement('td');
            td1.className = 'mono';
            td1.textContent = u.filename;
            var td2 = document.createElement('td');
            td2.textContent = formatBytes(u.size_bytes);
            var td3 = document.createElement('td');
            td3.textContent = u.uploaded_at || '--';
            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);
            tbody.appendChild(tr);
        });
    } catch (e) { console.error(e); }
}

// Init
checkAuth();
</script>
</body>
</html>"""


@app.route("/")
def index():
    """Redirect root to dashboard."""
    return redirect("/dashboard")


@app.route("/dashboard")
@app.route("/dashboard/device/<device_id>")
def dashboard(device_id=None):
    """Serve the fleet management dashboard."""
    return DASHBOARD_HTML


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    print(f"Sentinel server starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
else:
    # Also init DB on import so tests/workers get tables created
    init_db()
