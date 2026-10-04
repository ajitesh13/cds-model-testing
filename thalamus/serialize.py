"""Pure serializer: Patient -> computed header + row-ID'd text + record_hash."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from string import ascii_uppercase

from .record import Encounter, Patient

GA_SECTIONS = ("CHIEF_COMPLAINT", "HPI")
GA_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s*weeks?(?:'|’)?\s*(?:of\s+)?(?:gestation|gestational)", re.I),
    re.compile(r"\bat\s+(\d{1,2})\s*weeks?\b", re.I),
]
PREGNANCY_RE = re.compile(r"prenatal|pregnan|fetal|gestation|trimester", re.I)
ISO = r"(\d{4}-\d{2}-\d{2})"
LMP_RE = re.compile(r"\b(?:LMP|last menstrual period)\b[^0-9\n]{0,30}" + ISO, re.I)
EDD_RE = re.compile(r"\b(?:EDD|estimated (?:due date|date of delivery))\b[^0-9\n]{0,30}" + ISO, re.I)


@dataclass(frozen=True)
class Row:
    id: str
    text: str
    heading: str | None  # encounter heading for encounter rows, None for profile rows

    @property
    def searchable(self) -> str:
        return f"{self.text} {self.heading}" if self.heading else self.text


@dataclass
class Anchor:
    label: str
    weeks: int
    date: date
    sources: list[str]  # e.g. ["E4 CHIEF_COMPLAINT", "E4 HPI"]


@dataclass
class HeaderData:
    ages: list[tuple[int, date, int]] = field(default_factory=list)  # (encounter index, date, age)
    anchors: list[Anchor] = field(default_factory=list)
    dating: list[tuple[str, date, str]] = field(default_factory=list)  # (kind, date, source)
    pregnancy_encounters: list[int] = field(default_factory=list)
    # label -> [(encounter index, "17w0d")]
    ga: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    medications: list[str] = field(default_factory=list)
    medications_source: str = ""
    allergies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Serialized:
    header: str
    text: str
    record_hash: str
    rows: dict[str, Row]
    data: HeaderData


def sorted_encounters(patient: Patient) -> list[Encounter]:
    return sorted(patient.encounters, key=lambda e: (e.date, e.index))


def encounter_heading(e: Encounter) -> str:
    return f"=== E{e.index} | {e.date.isoformat()} | {e.department} | {e.type} | {e.attending} ==="


def iter_rows(patient: Patient):
    for name, rows in patient.profile.items():
        for k, text in enumerate(rows, 1):
            yield Row(f"P.{name}.{k}", text, None)
    for e in sorted_encounters(patient):
        heading = encounter_heading(e)
        for name, rows in e.sections.items():
            for k, text in enumerate(rows, 1):
                yield Row(f"E{e.index}.{name}.{k}", text, heading)


def format_ga(days: int) -> str:
    return f"{days // 7}w{days % 7}d"


def _years_between(start: date, end: date) -> int:
    return end.year - start.year - ((end.month, end.day) < (start.month, start.day))


def _first_age(patient: Patient) -> int | None:
    for row in patient.profile.get("AGE_AT_FIRST_ENCOUNTER", []):
        m = re.search(r"\d+", row)
        if m:
            return int(m.group())
    return None


def _stated_ga(e: Encounter) -> list[tuple[int, str]]:
    found = []
    for sec in GA_SECTIONS:
        for text in e.sections.get(sec, []):
            for pat in GA_PATTERNS:
                for m in pat.finditer(text):
                    w = int(m.group(1))
                    if 4 <= w <= 44:
                        found.append((w, sec))
    return found


def _is_pregnancy_related(e: Encounter) -> bool:
    if _stated_ga(e):
        return True
    return any(PREGNANCY_RE.search(t) for sec in GA_SECTIONS for t in e.sections.get(sec, []))


def compute_header(patient: Patient) -> HeaderData:
    data = HeaderData()
    encs = sorted_encounters(patient)
    if not encs:
        return data

    first_age = _first_age(patient)
    if first_age is not None:
        d0 = encs[0].date
        data.ages = [(e.index, e.date, first_age + _years_between(d0, e.date)) for e in encs]

    preg_start = next((i for i, e in enumerate(encs) if _is_pregnancy_related(e)), None)
    preg = encs[preg_start:] if preg_start is not None else []
    data.pregnancy_encounters = [e.index for e in preg]

    by_key: dict[tuple[date, int], Anchor] = {}
    for e in encs:
        for weeks, sec in _stated_ga(e):
            a = by_key.setdefault((e.date, weeks), Anchor("", weeks, e.date, []))
            src = f"E{e.index} {sec}"
            if src not in a.sources:
                a.sources.append(src)
    data.anchors = sorted(by_key.values(), key=lambda a: a.date)
    for label, a in zip(ascii_uppercase, data.anchors):
        a.label = label

    for e in encs:
        for sec, rows in e.sections.items():
            for text in rows:
                for kind, rx in (("LMP", LMP_RE), ("EDD", EDD_RE)):
                    for m in rx.finditer(text):
                        item = (kind, date.fromisoformat(m.group(1)), f"E{e.index} {sec}")
                        if all(item[:2] != d[:2] for d in data.dating):
                            data.dating.append(item)

    if data.dating:
        for kind, d, _ in data.dating:
            lmp = d if kind == "LMP" else d - timedelta(days=280)
            data.ga[f"{kind} {d.isoformat()}"] = [(e.index, format_ga((e.date - lmp).days)) for e in preg]
    else:
        for a in data.anchors:
            data.ga[a.label] = [
                (e.index, format_ga(a.weeks * 7 + (e.date - a.date).days)) for e in preg
            ]

    for e in reversed(encs):
        rows = [r for r in e.sections.get("MEDICATIONS", []) if not r.rstrip().endswith(":")]
        if e.sections.get("MEDICATIONS"):
            data.medications, data.medications_source = rows, f"E{e.index} MEDICATIONS"
            break
    else:
        data.medications = patient.profile.get("HOME_MEDICATIONS", [])
        data.medications_source = "profile HOME_MEDICATIONS"
    data.allergies = patient.profile.get("ALLERGIES", [])
    return data


def render_header(data: HeaderData) -> str:
    out = ["=== COMPUTED BY CODE (derived by software, not from clinical notes) ==="]
    if data.ages:
        out.append("Age at each encounter (approximate, no date of birth in record):")
        out.append("  " + " | ".join(f"E{i} ({d.isoformat()}): {a}" for i, d, a in data.ages))
    if data.anchors:
        out.append("Stated gestational age (regex over CHIEF_COMPLAINT and HPI):")
        for a in data.anchors:
            out.append(f"  Anchor {a.label}: {a.weeks} weeks on {a.date.isoformat()} ({', '.join(a.sources)})")
    if data.ga:
        pregs = ", ".join(f"E{i}" for i in data.pregnancy_encounters)
        if data.dating:
            out.append("Dating from LMP/EDD in record: " + "; ".join(f"{k} {d.isoformat()} ({s})" for k, d, s in data.dating))
        else:
            out.append("DATING UNCERTAIN: no LMP or EDD with a date in the record; each distinct stated gestational age is a separate anchor.")
        out.append(f"Gestational age at pregnancy-related encounters ({pregs}):")
        for label, vals in data.ga.items():
            name = label if data.dating else f"Anchor {label}"
            out.append(f"  {name}: " + " | ".join(f"E{i} {g}" for i, g in vals))
    out.append(f"Current medications ({data.medications_source}): " + ("; ".join(data.medications) or "none documented"))
    out.append("Allergies (profile): " + ("; ".join(data.allergies) or "none documented"))
    out.append("=== END COMPUTED ===")
    return "\n".join(out)


def serialize(patient: Patient) -> Serialized:
    data = compute_header(patient)
    header = render_header(data)
    rows = {r.id: r for r in iter_rows(patient)}

    parts = [header, "", "=== PATIENT PROFILE ==="]
    current_heading: str | None = None
    for r in iter_rows(patient):
        if r.heading and r.heading != current_heading:
            parts.append("")
            parts.append(r.heading)
            current_heading = r.heading
        parts.append(f"[{r.id}] {r.text}")
    text = "\n".join(parts) + "\n"
    return Serialized(header, text, hashlib.sha256(text.encode("utf-8")).hexdigest(), rows, data)
