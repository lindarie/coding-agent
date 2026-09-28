from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    workspace TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    ts REAL NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            # Runs left "running" by a crash/restart can never finish.
            self._db.execute(
                "UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'",
                (time.time(),),
            )
            self._db.commit()

    def create_run(self, run_id: str, task: str, workspace: str, model: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO runs (id, task, workspace, model, status, created_at) "
                "VALUES (?,?,?,?, 'running', ?)",
                (run_id, task, workspace, model, time.time()),
            )
            self._db.commit()

    def add_event(self, event: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events (run_id, seq, type, ts, payload) VALUES (?,?,?,?,?)",
                (event.run_id, event.seq, event.type, event.ts, event.model_dump_json()),
            )
            self._db.commit()

    def finish_run(self, run_id: str, status: str, summary: str | None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE runs SET status=?, summary=?, finished_at=? WHERE id=?",
                (status, summary, time.time(), run_id),
            )
            self._db.commit()

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                return None
            events = self._db.execute(
                "SELECT payload FROM events WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()
        out = dict(run)
        out["events"] = [json.loads(e["payload"]) for e in events]
        return out
