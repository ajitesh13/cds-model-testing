"""Adapter interface, config loading, retry/backoff, schema helper and cost."""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, TypeVar

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_YAML = ROOT / "configs" / "models.yaml"
PRICING_YAML = ROOT / "configs" / "pricing.yaml"
REQUEST_TIMEOUT_S = 600
MAX_ATTEMPTS = 3

T = TypeVar("T")


class ModelConfig(BaseModel):
    id: str
    provider: str
    model: str
    effort: str
    max_output_tokens: int = 32000


@dataclass
class Completion:
    text: str
    model_returned: str
    input_tokens: int          # total prompt tokens (uncached + cache reads + cache writes)
    output_tokens: int
    cached_input_tokens: int   # cache-read tokens
    latency_ms: int
    raw: dict = field(default_factory=dict)
    cache_write_tokens: int = 0
    retries: int = 0           # transient-error retries used (separate from schema/citation retries)


class ModelError(RuntimeError):
    """Non-transient provider failure (refusal, truncation, bad request)."""


class Adapter(Protocol):
    def complete(self, cfg: ModelConfig, system: str, record_block: str, question_block: str,
                 schema: type[BaseModel], history: list[dict] | None = None) -> Completion: ...


def load_configs(path: Path = MODELS_YAML) -> tuple[dict[str, ModelConfig], str]:
    """Returns ({id: ModelConfig}, default_config_id)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cap = data.get("max_output_tokens", 32000)
    cfgs = {c["id"]: ModelConfig(max_output_tokens=cap, **c) for c in data["configs"]}
    default = data.get("default") or next(iter(cfgs))
    if default not in cfgs:
        raise ValueError(f"default config {default!r} not in configs")
    return cfgs, default


def get_adapter(provider: str) -> Adapter:
    if provider == "anthropic":
        from .anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter()
    if provider == "openai":
        from .openai_adapter import OpenAIAdapter
        return OpenAIAdapter()
    raise ValueError(f"unknown provider {provider!r}")


def with_retries(call: Callable[[], T], is_transient: Callable[[Exception], bool], *,
                 max_attempts: int = MAX_ATTEMPTS, base_delay: float = 2.0,
                 sleep: Callable[[float], None] = time.sleep) -> tuple[T, int]:
    """Exponential backoff for transient errors. Returns (result, retries_used)."""
    for attempt in range(max_attempts):
        try:
            return call(), attempt
        except Exception as e:  # noqa: BLE001
            if attempt == max_attempts - 1 or not is_transient(e):
                raise
            sleep(base_delay * 2 ** attempt)
    raise AssertionError("unreachable")


def strict_json_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema -> structured-output schema: inline $refs, every object closed with all
    properties required, no defaults/titles."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
        out = {k: walk(v) for k, v in node.items() if k not in ("default", "title")}
        if out.get("type") == "object" or "properties" in out:
            props = out.get("properties", {})
            out["properties"] = props
            out["required"] = list(props)
            out["additionalProperties"] = False
        return out

    return walk(schema)


def load_pricing(path: Path = PRICING_YAML) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def cost_usd(cfg: ModelConfig, c: Completion, pricing: dict | None = None) -> float | None:
    """None => unknown (any needed price is null)."""
    p = (pricing if pricing is not None else load_pricing()).get(cfg.model) or {}
    inp, out, cached = p.get("input_per_mtok"), p.get("output_per_mtok"), p.get("cached_input_per_mtok")
    if inp is None or out is None:
        return None
    if c.cached_input_tokens and cached is None:
        return None
    uncached = c.input_tokens - c.cached_input_tokens
    total = uncached * inp + c.output_tokens * out + c.cached_input_tokens * (cached or 0)
    return total / 1_000_000
