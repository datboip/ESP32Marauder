-- Sentinel server schema — SQLite tables for device management,
-- config, command queue, and file uploads.

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT DEFAULT '',
    last_heartbeat TEXT,
    battery_pct INTEGER,
    scan_mode TEXT DEFAULT 'wardrive',
    free_heap INTEGER,
    lat REAL,
    lon REAL,
    uptime_sec INTEGER
);

CREATE TABLE IF NOT EXISTS config (
    device_id TEXT PRIMARY KEY,
    scan_mode TEXT DEFAULT 'wardrive',
    phone_home_interval_min INTEGER DEFAULT 30,
    dead_man_timeout_hrs INTEGER DEFAULT 48,
    active INTEGER DEFAULT 1,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    cmd TEXT NOT NULL,
    args TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    acked_at TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes INTEGER,
    uploaded_at TEXT DEFAULT (datetime('now')),
    filepath TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);
