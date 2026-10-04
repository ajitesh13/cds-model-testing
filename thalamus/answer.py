"""Answer schema and tolerant JSON parser."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ValidationError


class Claim(BaseModel):
    text: str
    type: Literal["documented", "computed", "inferred", "opinion"]
    cites: list[str] = []
    values: list[str] = []


class Conflict(BaseModel):
    topic: str
    rows: list[str]


class Answer(BaseModel):
    question_type: Literal["lookup", "timeline", "synthesis"]
    answer: str
    key_caveat: str | None
    details: list[str]
    claims: list[Claim]
    conflicts: list[Conflict]
    not_documented: list[str]


class AnswerParseError(ValueError):
    """Raised when model text is not valid JSON for the Answer schema. str(e) is fed back on retry."""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.S | re.I)


def strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return (m.group(1) if m else text).strip()


def parse_answer(text: str) -> Answer:
    body = strip_fences(text)
    try:
        return Answer.model_validate_json(body)
    except ValidationError as e:
        raise AnswerParseError(f"Response did not match the schema: {e}") from e
    except json.JSONDecodeError as e:  # defensive; pydantic wraps JSON errors in ValidationError
        raise AnswerParseError(f"Response was not valid JSON: {e}") from e
