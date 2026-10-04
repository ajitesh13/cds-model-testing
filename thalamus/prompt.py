"""Prompt assembly. The record block is byte-identical across questions so provider caching works."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = ROOT / "prompts" / "system_v1.md"


def load_system(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def prompt_version(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def record_block(serialized_text: str) -> str:
    return "PATIENT RECORD\n" + serialized_text


def question_block(question: str) -> str:
    return f"DOCTOR'S QUESTION: {question.strip()}"
