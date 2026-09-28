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
CREATE TABLE IF NOT EXISTS workspaces (
    name TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace, created_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, run_id);
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

    def list_runs(self, limit: int = 50, workspace: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM runs", []
        if workspace:
            sql += " WHERE workspace=?"
            args.append(workspace)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
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

    # ---- workspaces & file history ------------------------------------
    def add_workspace(self, name: str) -> float:
        """Remember when a workspace was created through the API. Returns created_at."""
        now = time.time()
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO workspaces (name, created_at) VALUES (?,?)", (name, now))
            self._db.commit()
        return now

    def workspace_stats(self) -> dict[str, dict[str, Any]]:
        """Per-workspace created_at (None if not created via the API) and run counts."""
        with self._lock:
            created = self._db.execute("SELECT name, created_at FROM workspaces").fetchall()
            runs = self._db.execute(
                "SELECT workspace, COUNT(*) AS n, MAX(created_at) AS last FROM runs GROUP BY workspace"
            ).fetchall()
        stats: dict[str, dict[str, Any]] = {}
        for r in created:
            stats[r["name"]] = {"created_at": r["created_at"], "run_count": 0, "last_run_at": None}
        for r in runs:
            st = stats.setdefault(r["workspace"], {"created_at": None, "run_count": 0, "last_run_at": None})
            st["run_count"], st["last_run_at"] = r["n"], r["last"]
        return stats

    def list_file_events(self, workspace: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Files the agent created/modified, newest first, taken from stored file_changed events."""
        sql = (
            "SELECT e.run_id, e.ts, e.payload, r.workspace, r.task FROM events e "
            "JOIN runs r ON r.id = e.run_id WHERE e.type = 'file_changed'"
        )
        args: list[Any] = []
        if workspace:
            sql += " AND r.workspace = ?"
            args.append(workspace)
        sql += " ORDER BY e.ts DESC, e.seq DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        out = []
        for r in rows:
            data = json.loads(r["payload"])
            out.append({
                "run_id": r["run_id"], "workspace": r["workspace"], "task": r["task"], "ts": r["ts"],
                "path": data.get("path", ""), "change": data.get("change", "modified"),
                "bytes": data.get("bytes", 0),
            })
        return out
