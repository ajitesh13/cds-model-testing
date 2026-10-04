"""SQLite storage for runs and ratings. DB at $DATA_DIR/thalamus.db (default ./var)."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, created_at TEXT, source TEXT,
  session_id TEXT, rater_label TEXT, question_id TEXT, question_text TEXT,
  config_id TEXT, provider TEXT, model_requested TEXT, model_returned TEXT, effort TEXT,
  prompt_version TEXT, record_hash TEXT,
  status TEXT CHECK (status IN ('verified','unverified','failed_schema','error')),
  answer_json TEXT, verification_json TEXT, format_checks_json TEXT, raw_response_json TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER, cost_usd REAL,
  latency_ms INTEGER, retries INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS ratings(
  rating_id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs(run_id), created_at TEXT,
  grade TEXT CHECK (grade IN ('correct','minor_error','major_error','unsafe')),
  comment TEXT, rater_label TEXT);
CREATE INDEX IF NOT EXISTS ratings_run ON ratings(run_id);
CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id, created_at);
"""

RUN_COLUMNS = [
    "run_id", "created_at", "source", "session_id", "rater_label", "question_id", "question_text",
    "config_id", "provider", "model_requested", "model_returned", "effort", "prompt_version", "record_hash",
    "status", "answer_json", "verification_json", "format_checks_json", "raw_response_json",
    "input_tokens", "output_tokens", "cached_input_tokens", "cost_usd", "latency_ms", "retries", "error",
]
RATING_COLUMNS = ["rating_id", "run_id", "created_at", "grade", "comment", "rater_label"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or "./var")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "thalamus.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _run(self, sql: str, args=()):
        c = self._conn()
        try:
            with c:
                return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def insert_run(self, **fields) -> str:
        fields.setdefault("run_id", uuid.uuid4().hex)
        fields.setdefault("created_at", now_iso())
        unknown = set(fields) - set(RUN_COLUMNS)
        if unknown:
            raise ValueError(f"unknown run columns: {unknown}")
        cols = list(fields)
        self._run(f"INSERT INTO runs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                  [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()])
        return fields["run_id"]

    def insert_rating(self, run_id: str, grade: str, comment: str = "", rater_label: str = "") -> str:
        rid = uuid.uuid4().hex
        self._run("INSERT INTO ratings(rating_id,run_id,created_at,grade,comment,rater_label) VALUES(?,?,?,?,?,?)",
                  (rid, run_id, now_iso(), grade, comment, rater_label))
        return rid

    def get_run(self, run_id: str) -> dict | None:
        rows = self._run("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return dict(rows[0]) if rows else None

    def list_runs(self, session_id: str | None = None) -> list[dict]:
        if session_id is None:
            rows = self._run("SELECT * FROM runs ORDER BY created_at, run_id")
        else:
            rows = self._run("SELECT * FROM runs WHERE session_id=? ORDER BY created_at, run_id", (session_id,))
        return [dict(r) for r in rows]

    def list_ratings(self, run_id: str | None = None) -> list[dict]:
        if run_id is None:
            rows = self._run("SELECT * FROM ratings ORDER BY created_at, rating_id")
        else:
            rows = self._run("SELECT * FROM ratings WHERE run_id=? ORDER BY created_at", (run_id,))
        return [dict(r) for r in rows]

    def export(self, fmt: str, out_dir: str | Path) -> list[Path]:
        import csv
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for name, rows, cols in (("runs", self.list_runs(), RUN_COLUMNS), ("ratings", self.list_ratings(), RATING_COLUMNS)):
            p = out / f"{name}.{fmt}"
            with p.open("w", encoding="utf-8", newline="") as f:
                if fmt == "jsonl":
                    for r in rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                elif fmt == "csv":
                    w = csv.DictWriter(f, fieldnames=cols)
                    w.writeheader()
                    w.writerows(rows)
                else:
                    raise ValueError("format must be jsonl or csv")
            written.append(p)
        return written
