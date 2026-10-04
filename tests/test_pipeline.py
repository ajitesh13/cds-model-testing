import json

import pytest
from typer.testing import CliRunner

from thalamus.adapters.base import Completion, load_configs
from thalamus.cli import app
from thalamus.evaluate import load_questions, run_eval
from thalamus.pipeline import ask, load_serialized
from thalamus.store import Store

CFG = load_configs()[0]["opus-high"]


def payload(value="3 cm", cites=("E7.IMAGING.1",), ctype="documented"):
    return json.dumps({
        "question_type": "lookup", "answer": "AFI 3 cm.", "key_caveat": None, "details": [],
        "claims": [{"text": "AFI", "type": ctype, "cites": list(cites), "values": [value]}],
        "conflicts": [], "not_documented": []})


class Fake:
    """Returns scripted texts in order; records histories."""
    def __init__(self, *texts, model="claude-opus-5-5-x"):
        self.texts, self.model, self.histories = list(texts), model, []

    def complete(self, cfg, system, rb, qb, schema, history=None):
        self.histories.append(history)
        return Completion(self.texts.pop(0), self.model, 100, 10, 60, 5, {"r": 1})


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


@pytest.fixture(scope="module")
def ser():
    return load_serialized()


def run(adapter, store, ser, **kw):
    return ask("What was the AFI?", CFG, source="cli", ser=ser, store=store, adapter=adapter, **kw)


def test_verified_first_try(store, ser):
    a = Fake(payload())
    r = run(a, store, ser)
    assert r.status == "verified" and len(a.histories) == 1
    row = store.get_run(r.run_id)
    assert row["status"] == "verified" and row["model_requested"] == "claude-opus-5-5" and row["effort"] == "high"
    assert row["record_hash"] == ser.record_hash and len(row["prompt_version"]) == 12
    assert row["cost_usd"] is None  # pricing.yaml all null => unknown


def test_citation_retry_fixes(store, ser):
    a = Fake(payload("5 cm"), payload("3 cm"))
    r = run(a, store, ser)
    assert r.status == "verified" and len(a.histories) == 2
    assert "5 cm" in a.histories[1][1]["content"] and a.histories[1][0]["role"] == "assistant"
    assert r.input_tokens == 200 and r.retries == 1


def test_citation_retry_still_wrong_is_unverified(store, ser):
    r = run(Fake(payload("5 cm"), payload("6 cm")), store, ser)
    assert r.status == "unverified" and r.answer is not None and r.verification["failures"]


def test_schema_retry(store, ser):
    a = Fake("not json", payload())
    r = run(a, store, ser)
    assert r.status == "verified" and "schema" in a.histories[1][1]["content"].lower()


def test_failed_schema(store, ser):
    r = run(Fake("nope", "still nope"), store, ser)
    assert r.status == "failed_schema" and r.answer is None and store.get_run(r.run_id)["answer_json"] is None


def test_model_mismatch_is_error(store, ser):
    r = run(Fake(payload(), model="claude-opus-4-8"), store, ser)
    assert r.status == "error" and "mismatch" in r.error and store.get_run(r.run_id)["status"] == "error"


def test_adapter_exception_is_error(store, ser):
    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("boom")
    r = run(Boom(), store, ser)
    assert r.status == "error" and "boom" in r.error


def test_store_and_export(store, ser, tmp_path):
    r = run(Fake(payload()), store, ser, session_id="s1", rater_label="dr x")
    assert [x["run_id"] for x in store.list_runs("s1")] == [r.run_id]
    assert store.list_runs("other") == []
    for fmt in ("jsonl", "csv"):
        paths = store.export(fmt, tmp_path / fmt)
        assert [p.name for p in paths] == [f"runs.{fmt}"] and r.run_id in paths[0].read_text()


def test_eval_resume_and_reports(tmp_path, store, monkeypatch):
    qs = load_questions("data/questions_2744.yaml")[:3]
    assert len(load_questions("data/questions_2744.yaml")) == 36
    qs[0]["answer_key"] = "3 cm"
    calls = []

    class Ad:
        def complete(self, cfg, *a, **k):
            calls.append(1)
            return Completion(payload(), cfg.model + "-d", 100, 10, 0, 7, {})

    out = tmp_path / "ev"
    run_eval("data/patient_2744.txt", qs, [CFG], concurrency=2, out_dir=out, store=store, adapter_for=lambda c: Ad())
    assert len(calls) == 3
    run_eval("data/patient_2744.txt", qs, [CFG], concurrency=2, out_dir=out, store=store, adapter_for=lambda c: Ad())
    assert len(calls) == 3  # resume skipped everything
    metrics = (out / "metrics.csv").read_text().splitlines()
    assert metrics[1].startswith("opus-high,3,100.0") and "100.0" in metrics[1] and metrics[1].endswith("unknown")
    grading = (out / "grading.csv").read_text()
    assert "opus-high" not in grading and "claude" not in grading  # blinded
    assert (out / "key.csv").read_text().count("opus-high") == 3


def test_cli_show_record_and_unknown_config(monkeypatch):
    r = CliRunner().invoke(app, ["show-record"])
    assert r.exit_code == 0 and "record_hash:" in r.output and "[E7.IMAGING.1]" in r.output
    assert CliRunner().invoke(app, ["ask", "q", "--config", "nope"]).exit_code != 0
