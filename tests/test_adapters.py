import os
from types import SimpleNamespace as NS

import anthropic
import httpx2 as httpx
import openai
import pytest

from thalamus.adapters.anthropic_adapter import AnthropicAdapter
from thalamus.adapters.anthropic_adapter import is_transient as a_transient
from thalamus.adapters.base import (Completion, ModelError, cost_usd, get_adapter, load_configs, strict_json_schema,
                                    with_retries)
from thalamus.adapters.openai_adapter import OpenAIAdapter
from thalamus.adapters.openai_adapter import is_transient as o_transient
from thalamus.answer import Answer

CFGS, DEFAULT = load_configs()
SCHEMA_JSON = '{"ok": 1}'


class Stream:
    def __init__(self, result, fail_times=0, exc=None, log=None):
        self.result, self.exc, self.log = result, exc, log
        log.setdefault("fail", fail_times)

    def __enter__(self):
        self.log["calls"] += 1
        if self.log["fail"] > 0:
            self.log["fail"] -= 1
            raise self.exc
        return self

    def __exit__(self, *a):
        return False

    get_final_message = get_final_response = lambda self: self.result


def anthropic_msg(**kw):
    base = dict(
        model="claude-opus-5-5-20260101", stop_reason="end_turn", stop_details=None,
        content=[NS(type="thinking", thinking=""), NS(type="text", text=SCHEMA_JSON)],
        usage=NS(input_tokens=50, output_tokens=700, cache_read_input_tokens=6000, cache_creation_input_tokens=0),
        model_dump=lambda mode="json": {"fake": True},
    )
    return NS(**{**base, **kw})


def fake_anthropic(msg, **sk):
    log = {"calls": 0, "kwargs": None}

    def stream(**kwargs):
        log["kwargs"] = kwargs
        return Stream(msg, log=log, **sk)

    return NS(messages=NS(stream=stream)), log


def test_default_config_is_opus_high():
    assert DEFAULT == "opus-high"
    c = CFGS[DEFAULT]
    assert (c.provider, c.model, c.effort) == ("anthropic", "claude-opus-5-5", "high")
    assert len(CFGS) == 6


def test_anthropic_request():
    client, log = fake_anthropic(anthropic_msg())
    ad = AnthropicAdapter(client)
    comp = ad.complete(CFGS["opus-high"], "SYS", "RECORD", "Q", Answer)
    k = log["kwargs"]
    assert k["model"] == "claude-opus-5-5" and k["system"] == "SYS" and k["max_tokens"] == 32000
    assert k["output_config"]["effort"] == "high"
    assert k["output_config"]["format"]["type"] == "json_schema"
    blocks = k["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "RECORD", "cache_control": {"type": "ephemeral"}}
    assert blocks[1] == {"type": "text", "text": "Q"}
    for forbidden in ("fallbacks", "betas", "thinking", "temperature", "extra_headers"):
        assert forbidden not in k
    # usage normalised: total input includes cache reads
    assert (comp.input_tokens, comp.cached_input_tokens, comp.output_tokens) == (6050, 6000, 700)
    assert comp.model_returned.startswith("claude-opus-5-5") and comp.text == SCHEMA_JSON


def test_anthropic_history_appended():
    client, log = fake_anthropic(anthropic_msg())
    hist = [{"role": "assistant", "content": "bad"}, {"role": "user", "content": "fix it"}]
    AnthropicAdapter(client).complete(CFGS["opus-high"], "S", "R", "Q", Answer, history=hist)
    msgs = log["kwargs"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"] and msgs[2]["content"] == "fix it"


@pytest.mark.parametrize("kw,err", [({"stop_reason": "refusal"}, "refused"), ({"stop_reason": "max_tokens"}, "truncated"),
                                    ({"content": []}, "no text")])
def test_anthropic_errors(kw, err):
    client, _ = fake_anthropic(anthropic_msg(**kw))
    with pytest.raises(ModelError, match=err):
        AnthropicAdapter(client).complete(CFGS["opus-high"], "S", "R", "Q", Answer)


def _status_err(cls, code):
    req = httpx.Request("POST", "https://x")
    return cls("e", response=httpx.Response(code, request=req), body=None)


def test_anthropic_retry_then_success():
    exc = _status_err(anthropic.InternalServerError, 500)
    client, log = fake_anthropic(anthropic_msg(), fail_times=2, exc=exc)
    sleeps = []
    comp = AnthropicAdapter(client, sleep=sleeps.append).complete(CFGS["opus-high"], "S", "R", "Q", Answer)
    assert log["calls"] == 3 and comp.retries == 2 and sleeps == [2.0, 4.0]


def test_retry_gives_up_after_3_and_skips_non_transient():
    exc = _status_err(anthropic.InternalServerError, 503)
    client, log = fake_anthropic(anthropic_msg(), fail_times=9, exc=exc)
    with pytest.raises(anthropic.InternalServerError):
        AnthropicAdapter(client, sleep=lambda s: None).complete(CFGS["opus-high"], "S", "R", "Q", Answer)
    assert log["calls"] == 3
    bad = _status_err(anthropic.BadRequestError, 400)
    client, log = fake_anthropic(anthropic_msg(), fail_times=9, exc=bad)
    with pytest.raises(anthropic.BadRequestError):
        AnthropicAdapter(client, sleep=lambda s: None).complete(CFGS["opus-high"], "S", "R", "Q", Answer)
    assert log["calls"] == 1


def test_transient_classification():
    req = httpx.Request("POST", "https://x")
    assert a_transient(_status_err(anthropic.RateLimitError, 429))
    assert a_transient(anthropic.APITimeoutError(request=req))
    assert not a_transient(_status_err(anthropic.AuthenticationError, 401))
    assert o_transient(_status_err(openai.RateLimitError, 429))
    assert o_transient(_status_err(openai.InternalServerError, 502))
    assert not o_transient(_status_err(openai.BadRequestError, 400))


def openai_resp(**kw):
    base = dict(
        model="gpt-6-astra-2026-09-01", status="completed", output_text=SCHEMA_JSON, error=None,
        incomplete_details=None, output=[NS(type="message", content=[NS(type="output_text", text=SCHEMA_JSON)])],
        usage=NS(input_tokens=6100, output_tokens=900, input_tokens_details=NS(cached_tokens=5900, cache_write_tokens=0)),
        model_dump=lambda mode="json": {"fake": True},
    )
    return NS(**{**base, **kw})


def fake_openai(resp, **sk):
    log = {"calls": 0, "kwargs": None}

    def stream(**kwargs):
        log["kwargs"] = kwargs
        return Stream(resp, log=log, **sk)

    return NS(responses=NS(stream=stream)), log


def test_openai_request_and_usage():
    client, log = fake_openai(openai_resp())
    comp = OpenAIAdapter(client).complete(CFGS["astra-high"], "SYS", "RECORD", "Q", Answer)
    k = log["kwargs"]
    assert k["model"] == "gpt-6-astra" and k["instructions"] == "SYS"
    assert k["reasoning"] == {"effort": "high"} and k["max_output_tokens"] == 32000
    fmt = k["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"]["additionalProperties"] is False
    parts = k["input"][0]["content"]  # record first so the prefix is cacheable
    assert [p["text"] for p in parts] == ["RECORD", "Q"]
    for forbidden in ("fallbacks", "betas", "temperature"):
        assert forbidden not in k
    assert (comp.input_tokens, comp.cached_input_tokens, comp.output_tokens) == (6100, 5900, 900)
    assert comp.model_returned.startswith("gpt-6-astra")


@pytest.mark.parametrize("kw,err", [
    ({"status": "incomplete", "incomplete_details": NS(reason="max_output_tokens")}, "incomplete"),
    ({"output": [NS(type="message", content=[NS(type="refusal", refusal="no")])]}, "refused"),
    ({"output_text": ""}, "no text"),
])
def test_openai_errors(kw, err):
    client, _ = fake_openai(openai_resp(**kw))
    with pytest.raises(ModelError, match=err):
        OpenAIAdapter(client).complete(CFGS["astra-high"], "S", "R", "Q", Answer)


def test_with_retries_backoff():
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] < 3:
            raise TimeoutError
        return "ok"

    sleeps = []
    assert with_retries(flaky, lambda e: True, sleep=sleeps.append) == ("ok", 2) and sleeps == [2.0, 4.0]


def test_strict_schema():
    s = strict_json_schema(Answer)
    assert "$defs" not in s and s["additionalProperties"] is False
    assert set(s["required"]) == set(Answer.model_fields)
    claim = s["properties"]["claims"]["items"]
    assert claim["required"] == ["text", "type", "cites", "values"] and claim["additionalProperties"] is False
    assert "default" not in claim["properties"]["cites"]


def test_cost_unknown_when_price_null_and_known_when_set():
    c = Completion("t", "m", 1_000_000, 100_000, 400_000, 1)
    assert cost_usd(CFGS["astra-high"], c) is None  # astra prices in pricing.yaml are still null
    pricing = {"claude-opus-5-5": {"input_per_mtok": 4.0, "output_per_mtok": 20.0, "cached_input_per_mtok": 0.4}}
    assert cost_usd(CFGS["opus-high"], c, pricing) == pytest.approx(0.6 * 4 + 0.1 * 20 + 0.4 * 0.4)
    assert cost_usd(CFGS["opus-high"], c, {"claude-opus-5-5": {**pricing["claude-opus-5-5"], "cached_input_per_mtok": None}}) is None


def test_cost_includes_cache_write_and_real_pricing_file():
    # Real run b15aecbd/d4fd3d17: 33 uncached + 9,466 cache-write input tokens, 1,089 output tokens.
    c = Completion("t", "m", 9499, 1089, 0, 1, cache_write_tokens=9466)
    assert cost_usd(CFGS["opus-high"], c) == pytest.approx((33 * 4 + 9466 * 5 + 1089 * 20) / 1e6)
    r = Completion("t", "m", 9499, 1089, 9466, 1)  # a cache read instead
    assert cost_usd(CFGS["opus-high"], r) == pytest.approx((33 * 4 + 9466 * 0.20 + 1089 * 20) / 1e6)
    assert cost_usd(CFGS["fable-high"], c) == pytest.approx((33 * 10 + 9466 * 12.5 + 1089 * 50) / 1e6)
    no_write_price = {"claude-opus-5-5": {"input_per_mtok": 4.0, "output_per_mtok": 20.0, "cached_input_per_mtok": 0.2}}
    assert cost_usd(CFGS["opus-high"], c, no_write_price) is None


def test_get_adapter():
    assert type(get_adapter("anthropic")).__name__ == "AnthropicAdapter"
    assert type(get_adapter("openai")).__name__ == "OpenAIAdapter"


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call real APIs")
@pytest.mark.parametrize("cfg_id", ["opus-medium", "astra-medium"])
def test_live_smoke(cfg_id):
    from thalamus.answer import parse_answer
    cfg = CFGS[cfg_id]
    comp = get_adapter(cfg.provider).complete(
        cfg, "Respond with JSON only.", "PATIENT RECORD\n[E1.HPI.1] Patient reports cough.",
        "DOCTOR'S QUESTION: What does the patient report?", Answer)
    assert comp.model_returned.startswith(cfg.model)
    parse_answer(comp.text)
