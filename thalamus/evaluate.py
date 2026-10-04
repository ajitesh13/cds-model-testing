"""Batch evaluation: every phrasing x config x repeat, resume-safe, blinded grading sheet."""
from __future__ import annotations

import csv
import json
import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

from .adapters.base import ModelConfig
from .pipeline import RunResult, ask, fmt_cost, load_serialized, render_text
from .store import Store, data_dir
from .verify import contains

METRIC_COLUMNS = ["config_id", "count", "verified_pct", "unverified_pct", "failed_schema_pct", "error_pct",
                  "format_compliance_pct", "answer_key_accuracy_pct", "mean_latency_ms", "p95_latency_ms",
                  "mean_cost_usd"]


def load_questions(path: str | Path) -> list[dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def new_eval_dir() -> Path:
    return data_dir() / "evals" / datetime.now().strftime("%Y%m%d-%H%M%S")


def job_key(qid: str, phrasing_idx: int, config_id: str, repeat: int) -> str:
    return f"{qid}|{phrasing_idx}|{config_id}|{repeat}"


def read_runs(out_dir: Path) -> list[dict]:
    p = out_dir / "runs.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_eval(patient_path, questions: list[dict], configs: list[ModelConfig], *, repeats: int = 1,
             concurrency: int = 4, out_dir: Path, store: Store | None = None, adapter_for=None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    store = store or Store()
    ser = load_serialized(patient_path)
    done = {r["key"] for r in read_runs(out_dir) if r["status"] != "error"}
    jobs = [(q, pi, text, cfg, rep) for q in questions for pi, text in enumerate(q["phrasings"])
            for cfg in configs for rep in range(repeats)
            if job_key(q["id"], pi, cfg.id, rep) not in done]
    sems = {p: threading.Semaphore(concurrency) for p in {c.provider for c in configs}}
    lock = threading.Lock()
    f = (out_dir / "runs.jsonl").open("a", encoding="utf-8")

    def work(job):
        q, pi, text, cfg, rep = job
        with sems[cfg.provider]:
            r: RunResult = ask(text, cfg, source="eval", ser=ser, store=store, question_id=q["id"],
                               adapter=adapter_for(cfg) if adapter_for else None)
        rec = {"key": job_key(q["id"], pi, cfg.id, rep), "question_id": q["id"], "tier": q.get("tier"),
               "phrasing_idx": pi, "question": text, "config_id": cfg.id, "repeat": rep, "run_id": r.run_id,
               "status": r.status, "answer": r.answer.model_dump() if r.answer else None,
               "verification": r.verification, "format_checks": r.format_checks,
               "model_returned": r.model_returned, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
               "cached_input_tokens": r.cached_input_tokens, "cost_usd": r.cost_usd, "latency_ms": r.latency_ms,
               "retries": r.retries, "error": r.error, "rendered": render_text(r)}
        with lock:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        return rec

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency * len(sems))) as ex:
            list(ex.map(work, jobs))
    finally:
        f.close()
    write_reports(out_dir, questions)
    return out_dir


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}" if d else ""


def _p95(xs: list[int]) -> int | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, -(-95 * len(s) // 100) - 1)]  # nearest rank


def _key_ok(rec: dict, key) -> bool:
    if not rec["answer"]:
        return False
    keys = key if isinstance(key, list) else [key]
    return any(contains(rec["answer"]["answer"], str(k)) for k in keys)


def write_reports(out_dir: Path, questions: list[dict]) -> None:
    runs = read_runs(out_dir)
    keys = {q["id"]: q.get("answer_key") for q in questions}
    rows = []
    for cid in sorted({r["config_id"] for r in runs}):
        rs = [r for r in runs if r["config_id"] == cid]
        n = len(rs)
        with_ans = [r for r in rs if r["answer"]]
        keyed = [r for r in rs if keys.get(r["question_id"]) is not None]
        costs = [r["cost_usd"] for r in rs if r["cost_usd"] is not None]
        lats = [r["latency_ms"] for r in rs if r["status"] != "error"]
        rows.append({
            "config_id": cid, "count": n,
            "verified_pct": _pct(sum(r["status"] == "verified" for r in rs), n),
            "unverified_pct": _pct(sum(r["status"] == "unverified" for r in rs), n),
            "failed_schema_pct": _pct(sum(r["status"] == "failed_schema" for r in rs), n),
            "error_pct": _pct(sum(r["status"] == "error" for r in rs), n),
            "format_compliance_pct": _pct(sum(all(c["passed"] for c in r["format_checks"]) for r in with_ans), len(with_ans)),
            "answer_key_accuracy_pct": _pct(sum(_key_ok(r, keys[r["question_id"]]) for r in keyed), len(keyed)),
            "mean_latency_ms": round(sum(lats) / len(lats)) if lats else "",
            "p95_latency_ms": _p95(lats) if lats else "",
            "mean_cost_usd": f"{sum(costs) / len(costs):.4f}" if costs else "unknown",
        })
    with (out_dir / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=METRIC_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    graded = [r for r in runs if r["status"] in ("verified", "unverified")]
    ids = {r["key"]: uuid.uuid4().hex[:8] for r in graded}
    random.shuffle(graded)
    with (out_dir / "grading.csv").open("w", encoding="utf-8", newline="") as g, \
            (out_dir / "key.csv").open("w", encoding="utf-8", newline="") as k:
        gw = csv.writer(g)
        kw = csv.writer(k)
        gw.writerow(["answer_id", "question", "answer", "grade", "comment"])
        kw.writerow(["answer_id", "config_id", "model_returned", "question_id", "phrasing_idx", "repeat", "status", "run_id"])
        for r in graded:
            gw.writerow([ids[r["key"]], r["question"], r["rendered"], "", ""])
            kw.writerow([ids[r["key"]], r["config_id"], r["model_returned"], r["question_id"], r["phrasing_idx"],
                         r["repeat"], r["status"], r["run_id"]])
