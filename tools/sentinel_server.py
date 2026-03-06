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

from flask import Flask, g, jsonify, request

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
