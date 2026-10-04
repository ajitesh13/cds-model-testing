"""Deterministic citation checker and format checks."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .answer import Answer
from .serialize import Row

WORD_CAPS = {"lookup": 60, "timeline": 150, "synthesis": 350}

_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ",
})
_NUM_UNIT_RE = re.compile(r"(\d)\s+(?=[a-z%°/])")
_TRAIL = " \t\n.,;:!?'\"()[]"


def normalize(s: str) -> str:
    s = s.translate(_TRANSLATE).lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = _NUM_UNIT_RE.sub(r"\1", s)
    return s.rstrip(_TRAIL)


def contains(haystack: str, value: str) -> bool:
    """Normalized substring match that does not start or end inside a word/number ('3 cm' != '13 cm')."""
    v = normalize(value)
    if not v:
        return False
    h = normalize(haystack)
    left = r"(?<![a-z0-9])" if v[0].isalnum() else ""
    right = r"(?![a-z0-9])" if v[-1].isalnum() else ""
    return re.search(left + re.escape(v) + right, h) is not None


@dataclass
class Failure:
    claim_index: int
    claim_text: str
    claim_type: str
    problem: str

    def __str__(self) -> str:
        return f'Claim {self.claim_index + 1} ({self.claim_type}) "{self.claim_text}": {self.problem}'


@dataclass
class Verification:
    ok: bool
    failures: list[Failure]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "failures": [asdict(f) for f in self.failures]}

    def retry_message(self) -> str:
        lines = "\n".join(f"- {f}" for f in self.failures)
        return (
            "Citation check failed for these claims:\n" + lines +
            "\nFix the claims: cite only row IDs that exist, copy values exactly from the cited rows "
            "(or from the computed header for computed claims), or retag the claim as inferred/opinion. "
            "Respond with JSON only, matching the schema."
        )


def verify_citations(answer: Answer, rows: dict[str, Row], header: str) -> Verification:
    failures: list[Failure] = []
    for i, c in enumerate(answer.claims):
        def fail(problem: str) -> None:
            failures.append(Failure(i, c.text, c.type, problem))

        if c.type == "documented":
            if not c.cites:
                fail("documented claim has no cited row IDs")
                continue
            missing = [r for r in c.cites if r not in rows]
            for r in missing:
                fail(f"cited row {r} does not exist in the record")
            found = [rows[r] for r in c.cites if r in rows]
            if not found:
                continue
            for v in c.values:
                if not any(contains(r.searchable, v) for r in found):
                    fail(f'value "{v}" not found in cited rows {", ".join(r.id for r in found)}')
        elif c.type == "computed":
            if not c.values:
                fail("computed claim has no values to check against the header")
            for v in c.values:
                if not contains(header, v):
                    fail(f'value "{v}" not found in the computed header')
    return Verification(ok=not failures, failures=failures)


def word_count(answer: Answer) -> int:
    parts = [answer.answer, answer.key_caveat or "", *answer.details]
    return sum(len(p.split()) for p in parts)


def format_checks(answer: Answer) -> list[dict]:
    """Logged only, never blocking."""
    cap = WORD_CAPS[answer.question_type]
    n = word_count(answer)
    needs_caveat = bool(answer.conflicts or answer.not_documented)
    return [
        {"check": "answer_non_empty", "passed": bool(answer.answer.strip()), "detail": ""},
        {"check": "word_cap", "passed": n <= cap, "detail": f"{n} words, cap {cap} for {answer.question_type}"},
        {"check": "caveat_present", "passed": (not needs_caveat) or bool(answer.key_caveat and answer.key_caveat.strip()),
         "detail": "key_caveat required when conflicts or not_documented is non-empty"},
    ]
