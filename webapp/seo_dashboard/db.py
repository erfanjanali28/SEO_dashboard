"""SQLite persistence for clients, sites, schedules, audits and synced metrics.

One file database (``SEO_DASHBOARD_DB`` env var, default ``webapp/data/dashboard.db``).
Audit results are stored as a JSON blob per audit plus a few denormalized
summary columns so trend charts do not need to load every blob.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("SEO_DASHBOARD_DATA", os.path.join(_BASE, "data"))
DB_PATH = os.environ.get("SEO_DASHBOARD_DB", os.path.join(DATA_DIR, "dashboard.db"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT,
    email TEXT,
    industry TEXT,
    notes TEXT,
    photo TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    industry TEXT,
    location TEXT,
    language TEXT DEFAULT 'en',
    max_pages INTEGER DEFAULT 150,
    interval_hours INTEGER DEFAULT 0,
    seed_keywords TEXT,
    competitors TEXT,
    windsor_gsc_account TEXT,
    windsor_ga4_account TEXT,
    last_run_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    progress TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    score INTEGER,
    pages_crawled INTEGER,
    issues_critical INTEGER,
    issues_high INTEGER,
    issues_medium INTEGER,
    issues_low INTEGER,
    result TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS search_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    query TEXT,
    page TEXT,
    clicks REAL,
    impressions REAL,
    ctr REAL,
    position REAL,
    source TEXT NOT NULL,
    UNIQUE(site_id, date, query, page, source)
);
CREATE TABLE IF NOT EXISTS analytics_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    landing_page TEXT,
    channel TEXT,
    sessions REAL,
    users REAL,
    engaged_sessions REAL,
    conversions REAL,
    UNIQUE(site_id, date, landing_page, channel)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_audits_site ON audits(site_id, started_at);
CREATE INDEX IF NOT EXISTS idx_sm_site ON search_metrics(site_id, date);
CREATE INDEX IF NOT EXISTS idx_am_site ON analytics_metrics(site_id, date);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def conn():
    with _lock:
        c = _connect()
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init_db() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def row(sql: str, params: tuple = ()) -> dict | None:
    with conn() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql: str, params: tuple = ()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def executemany(sql: str, seq: list[tuple]) -> None:
    with conn() as c:
        c.executemany(sql, seq)


def get_setting(key: str, default: str | None = None) -> str | None:
    r = row("SELECT value FROM settings WHERE key = ?", (key,))
    if r and r["value"]:
        return r["value"]
    return os.environ.get(key.upper(), default)


def set_setting(key: str, value: str | None) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def load_audit_result(audit: dict | None) -> dict | None:
    if not audit or not audit.get("result"):
        return None
    return json.loads(audit["result"])
