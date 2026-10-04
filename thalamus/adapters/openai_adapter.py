"""OpenAI Responses API adapter.

Verified against the OpenAI docs and installed SDK (2026-10): reasoning={"effort": ...}, max_output_tokens,
structured output via text.format json_schema (strict), automatic prefix caching (record block comes
first), usage.input_tokens_details.cached_tokens / cache_write_tokens. gpt-6-astra efforts:
low, medium, high, xhigh, max. No fallback parameters.
"""
from __future__ import annotations

import time

import openai
from pydantic import BaseModel

from .base import REQUEST_TIMEOUT_S, Completion, ModelConfig, ModelError, strict_json_schema, with_retries


def is_transient(e: Exception) -> bool:
    if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError)):
        return True
    return isinstance(e, openai.APIStatusError) and e.status_code >= 500


class OpenAIAdapter:
    def __init__(self, client: openai.OpenAI | None = None, sleep=time.sleep):
        self._client = client
        self._sleep = sleep

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            self._client = openai.OpenAI(max_retries=0, timeout=REQUEST_TIMEOUT_S)
        return self._client

    def build_request(self, cfg: ModelConfig, system: str, record_block: str, question_block: str,
                      schema: type[BaseModel], history: list[dict] | None = None) -> dict:
        user = {"role": "user", "content": [
            {"type": "input_text", "text": record_block},
            {"type": "input_text", "text": question_block},
        ]}
        return {
            "model": cfg.model,
            "instructions": system,
            "input": [user] + [{"role": m["role"], "content": m["content"]} for m in history or []],
            "reasoning": {"effort": cfg.effort},
            "max_output_tokens": cfg.max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": "answer",
                                "schema": strict_json_schema(schema), "strict": True}},
            "store": False,
        }

    def complete(self, cfg: ModelConfig, system: str, record_block: str, question_block: str,
                 schema: type[BaseModel], history: list[dict] | None = None) -> Completion:
        req = self.build_request(cfg, system, record_block, question_block, schema, history)

        def call():
            with self.client.responses.stream(**req) as stream:
                return stream.get_final_response()

        t0 = time.monotonic()
        resp, retries = with_retries(call, is_transient, sleep=self._sleep)
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status == "incomplete":
            raise ModelError(f"response incomplete: {getattr(resp.incomplete_details, 'reason', None)}")
        if resp.status == "failed":
            raise ModelError(f"response failed: {resp.error}")
        for item in resp.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "refusal":
                        raise ModelError(f"model refused: {part.refusal}")
        text = resp.output_text
        if not text:
            raise ModelError("response contained no text")

        u = resp.usage
        details = getattr(u, "input_tokens_details", None)
        return Completion(
            text=text,
            model_returned=resp.model,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cached_input_tokens=getattr(details, "cached_tokens", 0) or 0,
            cache_write_tokens=getattr(details, "cache_write_tokens", 0) or 0,
            latency_ms=latency_ms,
            raw=resp.model_dump(mode="json"),
            retries=retries,
        )
