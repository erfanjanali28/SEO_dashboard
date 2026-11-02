"""Recurring audits at a per-site interval (hours), set in the dashboard.

A single daemon thread wakes every minute, finds sites whose interval has
elapsed since ``last_run_at``, syncs Windsor.ai data when configured, and
starts an audit. Persisted in SQLite, so schedules survive restarts.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from . import audit, db
from .integrations import windsor

_thread: threading.Thread | None = None
_stop = threading.Event()


def due_sites() -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for s in db.rows("SELECT * FROM sites WHERE interval_hours > 0"):
        last = s.get("last_run_at")
        running = db.row("SELECT id FROM audits WHERE site_id = ? AND status = 'running'", (s["id"],))
        if running:
            continue
        if not last or (now - datetime.fromisoformat(last)).total_seconds() >= s["interval_hours"] * 3600:
            out.append(s)
    return out


def tick() -> list[int]:
    started = []
    for s in due_sites():
        if db.get_setting("windsor_api_key"):
            try:
                windsor.sync_site(s)
            except Exception:
                pass  # the audit still runs on crawl data alone
        db.execute("UPDATE sites SET last_run_at = ? WHERE id = ?", (db.now_iso(), s["id"]))
        started.append(audit.start_audit(s["id"]))
    return started


def _loop(interval: int):
    while not _stop.is_set():
        try:
            tick()
        except Exception:
            pass
        _stop.wait(interval)


def start(interval: int = 60) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    # Audits interrupted by a restart can never finish; mark them failed.
    db.execute("UPDATE audits SET status='error', error='Interrupted by restart' WHERE status='running'")
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,), daemon=True, name="seo-scheduler")
    _thread.start()


def stop() -> None:
    _stop.set()
    time.sleep(0)
