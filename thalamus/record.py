"""Loader for the patient export text format and its internal model."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel

# Synthetic-generator metadata. Not clinical data; must never reach the model.
DROPPED_KEYS = {"generation seed", "gen. method", "order"}

ENCOUNTER_RE = re.compile(r"^Encounter (\d+) — (\d{4}-\d{2}-\d{2}) — (.+?)\s*$")
SECTION_RE = re.compile(r"^\[([A-Z0-9_]+?)(?: \(modified\))?\]\s*$")
LIST_ITEM_RE = re.compile(r"^\s*-\s+(.*\S)\s*$")
KV_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 ./&-]*?):\s*(.*\S)?\s*$")
RULE_RE = re.compile(r"^[-=]{10,}\s*$")


class Encounter(BaseModel):
    index: int
    date: date
    department: str
    type: str
    attending: str
    encounter_id: str
    sections: dict[str, list[str]]


class Patient(BaseModel):
    profile: dict[str, list[str]]
    encounters: list[Encounter]


def section_key(name: str) -> str:
    """'Home Medications' -> 'HOME_MEDICATIONS'; 'Race/Ethnicity' -> 'RACE_ETHNICITY'."""
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def split_rows(lines: list[str]) -> list[str]:
    """A row is one non-empty paragraph or one list item."""
    rows: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            rows.append(" ".join(buf))
            buf.clear()

    for line in lines:
        if not line.strip():
            flush()
            continue
        m = LIST_ITEM_RE.match(line)
        if m:
            flush()
            rows.append(m.group(1))
        else:
            buf.append(line.strip())
    flush()
    return rows


def _split_pairs(line: str) -> list[tuple[str, str]]:
    """'Encounter ID: 1    Type: outpatient' -> [('Encounter ID','1'), ('Type','outpatient')]."""
    out = []
    for part in re.split(r"\s{2,}", line.strip()):
        m = KV_RE.match(part)
        if m:
            out.append((m.group(1).strip(), (m.group(2) or "").strip()))
    return out


def _parse_profile(lines: list[str]) -> dict[str, list[str]]:
    profile: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if not line.strip() or RULE_RE.match(line):
            continue
        item = LIST_ITEM_RE.match(line)
        if item and current:
            profile[current].append(item.group(1))
            continue
        m = KV_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).strip(), (m.group(2) or "").strip()
        if key.lower() in DROPPED_KEYS:
            current = None
        elif value:
            profile.setdefault(section_key(key), []).append(f"{key}: {value}")
            current = None
        else:
            current = section_key(key)
            profile.setdefault(current, [])
    return profile


def _parse_top_lists(lines: list[str]) -> dict[str, list[str]]:
    """Primary Diagnoses / Comorbidities from the top header; other top lines duplicate the profile."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        item = LIST_ITEM_RE.match(line)
        if item and current:
            out[current].append(item.group(1))
            continue
        m = re.match(r"^(Primary Diagnoses|Comorbidities):\s*$", line)
        current = section_key(m.group(1)) if m else None
        if m:
            out[current] = []
    return out


def _parse_encounter(head: re.Match, body: list[str]) -> Encounter:
    meta: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    i = 0
    while i < len(body) and not body[i].startswith("Structured EHR Sections"):
        for k, v in _split_pairs(body[i]):
            meta[k.lower()] = v
        i += 1
    current: str | None = None
    raw: dict[str, list[str]] = {}
    for line in body[i + 1:]:
        m = SECTION_RE.match(line)
        if m:
            current = m.group(1)
            raw.setdefault(current, [])
        elif current is not None:
            raw[current].append(line)
    for name, lines in raw.items():
        sections[name] = split_rows(lines)
    return Encounter(
        index=int(head.group(1)),
        date=date.fromisoformat(head.group(2)),
        department=head.group(3),
        type=meta.get("type", ""),
        attending=meta.get("attending", ""),
        encounter_id=meta.get("encounter id", ""),
        sections=sections,
    )


def parse_record(text: str) -> Patient:
    lines = text.splitlines()
    prof_at = next(i for i, l in enumerate(lines) if l.strip() == "PATIENT PROFILE")
    enc_at = next(i for i, l in enumerate(lines) if l.startswith("ENCOUNTERS"))
    top = _parse_top_lists(lines[:prof_at])
    profile = _parse_profile(lines[prof_at + 1:enc_at - 1])
    profile = {**top, **profile}

    encounters: list[Encounter] = []
    head: re.Match | None = None
    body: list[str] = []
    for line in lines[enc_at + 1:]:
        m = ENCOUNTER_RE.match(line)
        if m:
            if head:
                encounters.append(_parse_encounter(head, body))
            head, body = m, []
        elif head and not RULE_RE.match(line):
            body.append(line)
    if head:
        encounters.append(_parse_encounter(head, body))
    return Patient(profile=profile, encounters=encounters)


def load_record(path: str | Path) -> Patient:
    return parse_record(Path(path).read_text(encoding="utf-8"))
