"""Lightweight API health metrics: event-loop lag, DB session timing, WS counts.

Collects samples continuously and writes hourly snapshots to a dedicated
``data/health.db`` SQLite file (separate from the main alerts.db).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/health.db")

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS health_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ws_conns INTEGER,
    ws_peak INTEGER,
    loop_lag_avg_ms REAL,
    loop_lag_max_ms REAL,
    db_session_count INTEGER,
    db_avg_ms REAL,
    db_max_ms REAL,
    db_p95_ms REAL,
    threadpool_peak_queued INTEGER
)
"""

_INSERT = """\
INSERT INTO health_snapshot
    (ts, ws_conns, ws_peak, loop_lag_avg_ms, loop_lag_max_ms,
     db_session_count, db_avg_ms, db_max_ms, db_p95_ms, threadpool_peak_queued)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SAMPLE_INTERVAL = 0.5  # seconds between loop-lag probes


class _MetricsBucket:
    """Thread-safe accumulator for one reporting period."""

    def __init__(self):
        self._lock = threading.Lock()
        self._loop_lags: list[float] = []
        self._db_durations: list[float] = []
        self._ws_peak = 0
        self._ws_last = 0
        self._tp_queue_peak = 0

    def record_loop_lag(self, lag_s: float) -> None:
        with self._lock:
            self._loop_lags.append(lag_s * 1000.0)

    def record_db_session(self, elapsed_s: float) -> None:
        with self._lock:
            self._db_durations.append(elapsed_s * 1000.0)

    def record_ws_count(self, n: int) -> None:
        with self._lock:
            self._ws_last = n
            if n > self._ws_peak:
                self._ws_peak = n

    def record_tp_queue(self, depth: int) -> None:
        with self._lock:
            if depth > self._tp_queue_peak:
                self._tp_queue_peak = depth

    def rotate(self) -> dict:
        """Return summary and reset for next period."""
        with self._lock:
            lags = self._loop_lags
            dbs = self._db_durations
            summary = {
                "ws_conns": self._ws_last,
                "ws_peak": self._ws_peak,
                "loop_lag_avg_ms": _avg(lags),
                "loop_lag_max_ms": max(lags) if lags else 0.0,
                "db_session_count": len(dbs),
                "db_avg_ms": _avg(dbs),
                "db_max_ms": max(dbs) if dbs else 0.0,
                "db_p95_ms": _percentile(dbs, 95) if dbs else 0.0,
                "threadpool_peak_queued": self._tp_queue_peak,
            }
            self._loop_lags = []
            self._db_durations = []
            self._ws_peak = 0
            self._ws_last = 0
            self._tp_queue_peak = 0
        return summary


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _percentile(vals: list[float], pct: int) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * pct / 100.0
    f = int(k)
    c = f + 1
    if c >= len(s):
        return s[f]
    return s[f] + (k - f) * (s[c] - s[f])


# ---------------------------------------------------------------------------
# Module-level state (initialized by start())
# ---------------------------------------------------------------------------
_bucket: _MetricsBucket | None = None
_ws_manager = None


def record_db_session(elapsed_s: float) -> None:
    """Called from base.get_session(); no-op when monitor not started."""
    if _bucket is not None:
        _bucket.record_db_session(elapsed_s)


def get_snapshots(hours: int = 24) -> list[dict]:
    """Return recent health rows for the dashboard."""
    cutoff = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)).isoformat()
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM health_snapshot WHERE ts >= ? ORDER BY ts", (cutoff,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        logger.debug("health.db read failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def _loop_latency_sampler() -> None:
    loop = asyncio.get_running_loop()
    while True:
        t0 = loop.time()
        await asyncio.sleep(SAMPLE_INTERVAL)
        lag = loop.time() - t0 - SAMPLE_INTERVAL
        _bucket.record_loop_lag(lag)

        if _ws_manager is not None:
            with _ws_manager._lock:
                n = len(_ws_manager._connections)
            _bucket.record_ws_count(n)

        executor = loop._default_executor
        if executor is not None and hasattr(executor, "_work_queue"):
            try:
                _bucket.record_tp_queue(executor._work_queue.qsize())
            except Exception:
                pass


async def _hourly_reporter() -> None:
    _ensure_schema()
    while True:
        now = datetime.datetime.now(datetime.UTC)
        next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        await asyncio.sleep((next_hour - now).total_seconds())

        summary = _bucket.rotate()
        ts = next_hour.isoformat()

        try:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                _INSERT,
                (
                    ts,
                    summary["ws_conns"],
                    summary["ws_peak"],
                    summary["loop_lag_avg_ms"],
                    summary["loop_lag_max_ms"],
                    summary["db_session_count"],
                    summary["db_avg_ms"],
                    summary["db_max_ms"],
                    summary["db_p95_ms"],
                    summary["threadpool_peak_queued"],
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            logger.exception("Failed to write health snapshot")

        logger.info(
            "HEALTH hourly | ws=%d (peak=%d) | loop_ms avg=%.1f max=%.1f"
            " | db=%d avg=%.1f max=%.1f p95=%.1f | tp_queue_peak=%d",
            summary["ws_conns"],
            summary["ws_peak"],
            summary["loop_lag_avg_ms"],
            summary["loop_lag_max_ms"],
            summary["db_session_count"],
            summary["db_avg_ms"],
            summary["db_max_ms"],
            summary["db_p95_ms"],
            summary["threadpool_peak_queued"],
        )


def _ensure_schema() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_TABLE)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def start(ws_mgr) -> None:
    """Launch background sampler and reporter tasks on the current event loop."""
    global _bucket, _ws_manager
    _bucket = _MetricsBucket()
    _ws_manager = ws_mgr

    from roboToald.db import base

    base._record_session_duration = record_db_session

    asyncio.create_task(_loop_latency_sampler())
    asyncio.create_task(_hourly_reporter())
    logger.info("Health monitor started (db=%s)", _DB_PATH)
