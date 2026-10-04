"""Run storage. SQLite at $DATA_DIR/thalamus.db (default ./var) is the default and the local fallback;
set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY and make_store() returns SupabaseStore (table thalamus_harness_runs)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.parse
import urllib.request
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
  input_tokens INTEGER, output_tokens INTEGER, cached_input_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL,
  latency_ms INTEGER, retries INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id, created_at);
"""

RUN_COLUMNS = [
    "run_id", "created_at", "source", "session_id", "rater_label", "question_id", "question_text",
    "config_id", "provider", "model_requested", "model_returned", "effort", "prompt_version", "record_hash",
    "status", "answer_json", "verification_json", "format_checks_json", "raw_response_json",
    "input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "cost_usd", "latency_ms", "retries", "error",
]
# Stored by SupabaseStore only; SQLite drops them silently.
EXTRA_COLUMNS = ["turn_index", "patient", "client_ip", "origin", "user_agent", "canonical_question", "cache_hit"]
JSON_COLUMNS = ["answer_json", "verification_json", "format_checks_json", "raw_response_json"]
TABLE = "thalamus_harness_runs"
TIMEOUT_S = 10
log = logging.getLogger("thalamus.store")


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
            if "cache_write_tokens" not in {r["name"] for r in c.execute("PRAGMA table_info(runs)")}:
                c.execute("ALTER TABLE runs ADD COLUMN cache_write_tokens INTEGER")  # DB made before this column

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
        for k in EXTRA_COLUMNS:
            fields.pop(k, None)
        unknown = set(fields) - set(RUN_COLUMNS)
        if unknown:
            raise ValueError(f"unknown run columns: {unknown}")
        cols = list(fields)
        self._run(f"INSERT INTO runs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                  [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()])
        return fields["run_id"]

    def get_run(self, run_id: str) -> dict | None:
        rows = self._run("SELECT * FROM runs WHERE run_id=?", (run_id,))
        return dict(rows[0]) if rows else None

    def list_runs(self, session_id: str | None = None) -> list[dict]:
        if session_id is None:
            rows = self._run("SELECT * FROM runs ORDER BY created_at, run_id")
        else:
            rows = self._run("SELECT * FROM runs WHERE session_id=? ORDER BY created_at, run_id", (session_id,))
        return [dict(r) for r in rows]

    def export(self, fmt: str, out_dir: str | Path) -> list[Path]:
        return write_export(self.list_runs(), fmt, out_dir)


def write_export(rows: list[dict], fmt: str, out_dir: str | Path) -> list[Path]:
    import csv
    if fmt not in ("jsonl", "csv"):
        raise ValueError("format must be jsonl or csv")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"runs.{fmt}"
    with p.open("w", encoding="utf-8", newline="") as f:
        if fmt == "jsonl":
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        else:
            w = csv.DictWriter(f, fieldnames=RUN_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return [p]


class SupabaseStore:
    """Runs in Supabase Postgres via PostgREST, written with the service_role key (RLS has no policies).

    Same interface as Store. JSON columns are returned as JSON strings, as Store does. A failed write is
    logged and the run goes to the local SQLite fallback instead, so a Supabase outage never loses a run
    or breaks the answer. Reads need Supabase and raise on failure.
    """

    def __init__(self, url: str, key: str, fallback: Store | None = None):
        self.url, self.key = url.rstrip("/"), key
        self.fallback = fallback or Store()

    def _request(self, method: str, query: str = "", body=None, prefer: str | None = None):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(f"{self.url}/rest/v1/{TABLE}{query}", method=method, headers=headers,
                                     data=json.dumps(body, default=str).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def insert_run(self, **fields) -> str:
        fields.setdefault("run_id", str(uuid.uuid4()))
        fields.setdefault("created_at", now_iso())
        unknown = set(fields) - set(RUN_COLUMNS) - set(EXTRA_COLUMNS)
        if unknown:
            raise ValueError(f"unknown run columns: {unknown}")
        row = {("id" if k == "run_id" else k): v for k, v in fields.items()}
        for k in JSON_COLUMNS:
            if isinstance(row.get(k), str):
                row[k] = json.loads(row[k])
        try:
            self._request("POST", body=row, prefer="return=minimal")
        except Exception:
            log.exception("Supabase write failed; run %s saved to local SQLite fallback", fields["run_id"])
            self.fallback.insert_run(**fields)
        return fields["run_id"]

    @staticmethod
    def _to_run(row: dict) -> dict:
        out = {("run_id" if k == "id" else k): v for k, v in row.items()}
        for k in JSON_COLUMNS:
            if out.get(k) is not None:
                out[k] = json.dumps(out[k])
        return out

    def get_run(self, run_id: str) -> dict | None:
        rows = self._request("GET", f"?id=eq.{urllib.parse.quote(run_id)}")
        return self._to_run(rows[0]) if rows else None

    def list_runs(self, session_id: str | None = None) -> list[dict]:
        flt = f"session_id=eq.{urllib.parse.quote(session_id)}&" if session_id is not None else ""
        out, page = [], 1000
        while True:  # PostgREST caps a response; page until a short page comes back
            rows = self._request("GET", f"?{flt}order=created_at,id&limit={page}&offset={len(out)}")
            out += [self._to_run(r) for r in rows]
            if len(rows) < page:
                return out

    def export(self, fmt: str, out_dir: str | Path) -> list[Path]:
        return write_export(self.list_runs(), fmt, out_dir)


def make_store() -> Store | SupabaseStore:
    """SupabaseStore when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set, else local SQLite."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    return SupabaseStore(url, key) if url and key else Store()
