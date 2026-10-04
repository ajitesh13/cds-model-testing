"""ask(): record -> prompt -> one model call (+ at most one schema retry, one citation retry) -> verify -> log."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.base import Completion, ModelConfig, cost_usd, get_adapter
from .answer import Answer, AnswerParseError, parse_answer
from .prompt import load_system, prompt_version, question_block, record_block
from .record import load_record
from .serialize import Serialized, serialize
from .store import Store, SupabaseStore, make_store
from .verify import Verification, format_checks, verify_citations

DEFAULT_PATIENT = Path(__file__).resolve().parent.parent / "data" / "patient_2744.txt"


@dataclass
class RunResult:
    run_id: str
    status: str
    config_id: str
    question: str
    answer: Answer | None = None
    verification: dict = field(default_factory=dict)
    format_checks: list = field(default_factory=list)
    model_returned: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    retries: int = 0
    error: str | None = None
    rows: dict = field(default_factory=dict)  # row id -> Row, for rendering citations


def load_serialized(patient_path: str | Path = DEFAULT_PATIENT) -> Serialized:
    return serialize(load_record(patient_path))


def _model_ok(cfg: ModelConfig, comp: Completion) -> bool:
    return comp.model_returned.startswith(cfg.model)


def ask(question: str, cfg: ModelConfig, *, source: str, ser: Serialized | None = None,
        patient_path: str | Path = DEFAULT_PATIENT, store: Store | SupabaseStore | None = None, adapter=None,
        session_id: str | None = None, rater_label: str | None = None, question_id: str | None = None,
        pricing: dict | None = None, extra: dict | None = None) -> RunResult:
    store = store or make_store()
    ser = ser or load_serialized(patient_path)
    system, rb, qb = load_system(), record_block(ser.text), question_block(question)
    calls: list[Completion] = []
    result = RunResult(run_id="", status="error", config_id=cfg.id, question=question, rows=ser.rows)
    answer: Answer | None = None
    verification: Verification | None = None
    status, error = "error", None

    def call(history=None) -> Completion:
        comp = (adapter or get_adapter(cfg.provider)).complete(cfg, system, rb, qb, Answer, history)
        calls.append(comp)
        if not _model_ok(cfg, comp):
            raise RuntimeError(f"model mismatch: requested {cfg.model!r}, returned {comp.model_returned!r}")
        return comp

    try:
        comp = call()
        try:
            answer = parse_answer(comp.text)
        except AnswerParseError as e:  # schema retry (at most one)
            history = [{"role": "assistant", "content": comp.text},
                       {"role": "user", "content": f"{e}\nRespond again with JSON only, matching the schema."}]
            comp = call(history)
            try:
                answer = parse_answer(comp.text)
            except AnswerParseError as e2:
                status, error = "failed_schema", str(e2)

        if answer is not None:
            verification = verify_citations(answer, ser.rows, ser.header)
            if not verification.ok:  # citation retry (at most one)
                history = [{"role": "assistant", "content": comp.text},
                           {"role": "user", "content": verification.retry_message()}]
                comp2 = call(history)
                try:
                    answer2 = parse_answer(comp2.text)
                    answer, verification = answer2, verify_citations(answer2, ser.rows, ser.header)
                except AnswerParseError:
                    pass  # keep the first answer, still unverified
            status = "verified" if verification.ok else "unverified"
    except Exception as e:  # noqa: BLE001 - any provider/mismatch failure is logged as an error run
        status, error = "error", f"{type(e).__name__}: {e}"

    last = calls[-1] if calls else None
    tot = lambda f: sum(getattr(c, f) for c in calls)  # noqa: E731
    cost = None
    if calls:
        parts = [cost_usd(cfg, c, pricing) for c in calls]
        cost = None if any(p is None for p in parts) else sum(parts)
    fmt = format_checks(answer) if answer else []
    result.__dict__.update(
        status=status, answer=answer, verification=verification.to_dict() if verification else {},
        format_checks=fmt, model_returned=last.model_returned if last else "",
        input_tokens=tot("input_tokens"), output_tokens=tot("output_tokens"),
        cached_input_tokens=tot("cached_input_tokens"),
        cache_write_tokens=tot("cache_write_tokens"), cost_usd=cost, latency_ms=tot("latency_ms"),
        retries=tot("retries") + max(len(calls) - 1, 0), error=error,
    )
    result.run_id = store.insert_run(
        source=source, session_id=session_id, rater_label=rater_label, question_id=question_id,
        question_text=question, config_id=cfg.id, provider=cfg.provider, model_requested=cfg.model,
        model_returned=result.model_returned, effort=cfg.effort, prompt_version=prompt_version(),
        record_hash=ser.record_hash, status=status,
        answer_json=answer.model_dump_json() if answer else None,
        verification_json=json.dumps(result.verification), format_checks_json=json.dumps(fmt),
        raw_response_json=json.dumps([c.raw for c in calls]), input_tokens=result.input_tokens,
        output_tokens=result.output_tokens, cached_input_tokens=result.cached_input_tokens,
        cache_write_tokens=result.cache_write_tokens,
        cost_usd=cost, latency_ms=result.latency_ms, retries=result.retries, error=error,
        patient=Path(patient_path).stem, **(extra or {}),
    )
    return result


def fmt_cost(c: float | None) -> str:
    return "unknown" if c is None else f"${c:.4f}"


def render_text(result: RunResult) -> str:
    """Plain-text rendering of an answer (CLI and blinded grading sheet)."""
    a = result.answer
    if a is None:
        return f"[{result.status}] {result.error or ''}".strip()
    out = [f"ANSWER: {a.answer}"]
    if a.key_caveat:
        out.append(f"KEY CAVEAT: {a.key_caveat}")
    if a.details:
        out.append("DETAILS:\n" + "\n".join(f"- {d}" for d in a.details))
    cited = list(dict.fromkeys(r for c in a.claims for r in c.cites))
    if cited:
        out.append("CITED ROWS:\n" + "\n".join(
            f"- [{r}] {result.rows[r].text if r in result.rows else '(row not found)'}" for r in cited))
    if a.conflicts:
        out.append("CONFLICTS:\n" + "\n".join(f"- {c.topic}: {', '.join(c.rows)}" for c in a.conflicts))
    if a.not_documented:
        out.append("NOT DOCUMENTED:\n" + "\n".join(f"- {n}" for n in a.not_documented))
    out.append(f"STATUS: {result.status}")
    return "\n".join(out)
