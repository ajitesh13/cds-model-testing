# Thalamus: Product Intent

## Aim

Let a doctor ask any question about a patient's medical history and get an answer that is **accurate, traceable to the record, and the same no matter how the question is phrased.**

## The problem it solves

A patient's history is scattered across years of visits, specialties and notes, often with contradictions and gaps (patient 2744 had four different versions of her obstetric history). A doctor doesn't have time to read all of it before a consultation. So they either miss things or rely on memory and the latest note.

## What the product does

The doctor asks a question in their own words, however rough. Thalamus answers from the full longitudinal record and:

- puts the direct answer first, then the most important caveat
- cites the exact record line behind every fact, so the doctor can check it
- flags conflicts in the record and says what's undocumented, instead of guessing
- answers the same intent the same way every time, however it's phrased

## The three intents

Every action on this project must move toward these three results.

### 1. Clinically accurate

The answer is correct. Facts match the record, dates and ages are computed by code (never by the model), conflicts in the record are surfaced rather than silently resolved, and anything undocumented is said to be undocumented rather than guessed.

### 2. Traceable

Every fact cites the exact record line behind it, so the doctor can check it. Citations are verified in code against the cited row. The direct answer comes first, then the most important caveat, so the doctor can act on it fast and verify it quickly.

### 3. Deterministic

The same clinical intent gets the same answer every time, however it is phrased. This comes from the architecture (canonical questions plus caching, policy rules in the prompt), not from model settings.

## What success looks like

A doctor trusts an answer enough to act on it, because it is verifiable rather than just plausible. In this domain, trust comes from consistency and citations more than from eloquence.

## What phases 1 to 3 are for

Proving that this works reliably for a single patient before building anything bigger.

| Phase | Purpose | Serves |
| --- | --- | --- |
| 1. Basic harness | Build the test bench: ask, send prompt and record, get a cited and checked answer, log everything | Traceable; makes accuracy and determinism measurable |
| 2. Model selection | Use the bench to pick the right model and effort with evidence, graded by doctors | Clinically accurate |
| 3. Determinism | Make answers the same for the same intent | Deterministic |

Only once this holds for one patient does it make sense to invest in multiple patients, real data, compliance infrastructure and a proper product.

## How to use this document

Before adding or changing anything, ask which of the three intents it serves. If the answer is none, don't build it. If a choice trades one intent against another, record the decision and the reason in the decisions log.

Examples of the test in practice:

- Ratings and the eval flow were cut from phase 1 because they don't serve the harness. They return in phase 2, where they serve accuracy.
- Code-computed ages and gestational-age anchors serve accuracy.
- The citation verifier serves traceability and accuracy.
- Caching serves determinism, but a cached wrong answer breaks accuracy. That is why canonical answer review is required.

See `PHASED_IMPLEMENTATION_PLAN.md` for the build plan.
