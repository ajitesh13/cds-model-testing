"""Anthropic Messages API adapter.

Verified against the Claude API docs (2026-10): effort via output_config.effort, structured output
via output_config.format (json_schema), cache_control on the record content block, streaming with
get_final_message(), usage.cache_read_input_tokens / cache_creation_input_tokens. Thinking is always
on for these models, so no `thinking` or sampling params are sent. No fallbacks parameter or beta.
"""
from __future__ import annotations

import time

import anthropic
from pydantic import BaseModel

from .base import REQUEST_TIMEOUT_S, Completion, ModelConfig, ModelError, strict_json_schema, with_retries


def is_transient(e: Exception) -> bool:
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError)):
        return True
    return isinstance(e, anthropic.APIStatusError) and e.status_code >= 500


class AnthropicAdapter:
    def __init__(self, client: anthropic.Anthropic | None = None, sleep=time.sleep):
        self._client = client
        self._sleep = sleep

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            # SDK retries off: we do our own bounded backoff so retries are counted and logged.
            self._client = anthropic.Anthropic(max_retries=0, timeout=REQUEST_TIMEOUT_S)
        return self._client

    def build_request(self, cfg: ModelConfig, system: str, record_block: str, question_block: str,
                      schema: type[BaseModel], history: list[dict] | None = None) -> dict:
        messages = [{"role": "user", "content": [
            {"type": "text", "text": record_block, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": question_block},
        ]}]
        messages += [{"role": m["role"], "content": m["content"]} for m in history or []]
        return {
            "model": cfg.model,
            "max_tokens": cfg.max_output_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"effort": cfg.effort,
                              "format": {"type": "json_schema", "schema": strict_json_schema(schema)}},
        }

    def complete(self, cfg: ModelConfig, system: str, record_block: str, question_block: str,
                 schema: type[BaseModel], history: list[dict] | None = None) -> Completion:
        req = self.build_request(cfg, system, record_block, question_block, schema, history)

        def call():
            with self.client.messages.stream(**req) as stream:
                return stream.get_final_message()

        t0 = time.monotonic()
        msg, retries = with_retries(call, is_transient, sleep=self._sleep)
        latency_ms = int((time.monotonic() - t0) * 1000)

        if msg.stop_reason == "refusal":
            raise ModelError(f"model refused (stop_details={getattr(msg, 'stop_details', None)})")
        if msg.stop_reason == "max_tokens":
            raise ModelError("output truncated at max_tokens")
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if text is None:
            raise ModelError("response contained no text block")

        u = msg.usage
        read = getattr(u, "cache_read_input_tokens", 0) or 0
        write = getattr(u, "cache_creation_input_tokens", 0) or 0
        return Completion(
            text=text,
            model_returned=msg.model,
            input_tokens=(u.input_tokens or 0) + read + write,  # Anthropic's input_tokens excludes cache tokens
            output_tokens=u.output_tokens or 0,
            cached_input_tokens=read,
            cache_write_tokens=write,
            latency_ms=latency_ms,
            raw=msg.model_dump(mode="json"),
            retries=retries,
        )
