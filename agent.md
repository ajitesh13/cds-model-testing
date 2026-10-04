# Thalamus: Agent Guide

Entry point for any agent or engineer working in this repo. Read this first, then the docs it points to.

## What this project is

Thalamus is an OB/GYN clinical decision support (CDS) test harness. A doctor asks a question about one patient (synthetic patient 2744). The system prompt, a code-computed header and the full serialized record go to a selectable LLM in one call. The answer comes back as JSON with cited record rows. Code verifies every citation. Every run is logged to SQLite. A Streamlit app behind a static login serves testers.

Scope: one patient at a time, synthetic data only, obstetrics and gynecology. No real patient data until after phase 3 and DPDP-compliant infrastructure.

## Governing rule

Every change must serve one of the three intents in [docs/PRODUCT_INTENT.md](docs/PRODUCT_INTENT.md):

1. **Clinically accurate**: facts match the record, code computes dates and ages, conflicts are surfaced, undocumented items are stated as undocumented.
2. **Traceable**: every fact cites the exact record row, verified in code. Direct answer first, then the key caveat.
3. **Deterministic**: the same intent gets the same answer however it is phrased. Comes from architecture (canonical questions, caching, policy rules), not model settings.

Before building anything, say which intent it serves. If none, don't build it. If a choice trades one intent against another, record the decision and reason in the decisions log.

## Docs (in `docs/`)

| Doc | Read it for |
| --- | --- |
| [docs/PRODUCT_INTENT.md](docs/PRODUCT_INTENT.md) | Aim, the three intents, what success looks like, how to test any proposed work |
| [docs/PHASED_IMPLEMENTATION_PLAN.md](docs/PHASED_IMPLEMENTATION_PLAN.md) | Phases 1 to 3: tasks, exit criteria, decisions made, what is open |
| [README.md](README.md) | Run locally, env vars, deployment notes |

## Phases and current status

| Phase | Goal | Status |
| --- | --- | --- |
| 1. Basic harness | Ask, send prompt and record, get a cited and checked answer, log everything | Code complete (81 tests pass, 2 live skipped). Anthropic verified live (model ID, cache, Supabase write). Open: OpenAI smoke call and pricing, spend-capped keys, Docker build, deploy |
| 2. Model selection | Pick model and effort from six configs using doctor-graded evidence | Not started. Eval runner and ratings return here |
| 3. Determinism | Canonicalizer, answer cache, always-on flags block, policy rules | Not started |

Phase 1 is the harness only. The eval runner and ratings were removed on purpose; a doctor reviews answers manually. Details and the open checklist live in the plan doc. Do not duplicate them here.

## Repository map

| Path | Purpose |
| --- | --- |
| `thalamus/record.py` | Parse the patient export; drop synthetic-generator metadata |
| `thalamus/serialize.py` | Deterministic serialization with row IDs (`E{n}.{SECTION}.{k}`, `P.{SECTION}.{k}`); computed header (ages, GA anchors, LMP/EDD); `record_hash` = SHA-256 of the text |
| `thalamus/prompt.py` | Assemble system prompt, header, record, question. Record comes first for prefix caching |
| `thalamus/answer.py` | Answer schema (pydantic) and JSON parsing |
| `thalamus/verify.py` | Citation verifier: normalized, boundary-aware matching against the cited row. Format checks are logged, not blocking |
| `thalamus/adapters/` | `base.py` (retry, backoff, model-ID check), `anthropic_adapter.py`, `openai_adapter.py` |
| `thalamus/pipeline.py` | One call per question, plus at most one schema retry and one citation retry. Status: `verified`, `unverified`, `failed_schema`, `error` |
| `thalamus/store.py` | `Store` (SQLite `runs`, WAL) and `SupabaseStore` (table `thalamus_harness_runs`, PostgREST, SQLite fallback on write failure). `make_store()` picks by env |
| `supabase/migrations/` | Migration for `thalamus_harness_runs` (same Supabase project as `thalamus_chat_log`; not yet applied) |
| `thalamus/cli.py` | `ask`, `show-record`, `export` |
| `app.py` | Streamlit app: `hmac.compare_digest` login, blind or choose model mode, verified/unverified badge, session history |
| `configs/models.yaml` | Six configs; default `opus-high` (`claude-opus-5-5`, effort high) |
| `configs/pricing.yaml` | USD per million tokens (input, output, cache read, cache write). Anthropic filled; OpenAI null so cost shows "unknown" |
| `prompts/system_v1.md` | System prompt v1 (house rules, three answer shapes) |
| `data/` | `patient_2744.txt`, `questions_2744.txt` (36 questions) |
| `tests/` | Offline tests with mocked adapters; live tests need `RUN_LIVE=1` |
| `reference/legacy/` | Old curl scripts that use fallbacks. Do not reuse |
| `Dockerfile` | Image for deployment, data at `/data` |

## Hard rules

- **No fallbacks.** Never configure a fallback model or server-side fallback. A returned model ID that differs from the requested one makes the run an `error`.
- **Code does date and age math.** The model never computes ages, gestational ages or dates.
- **Whole record in the prompt.** No RAG, no vector database.
- **Secrets from the environment only.** Never commit `.env`. Never read `.env` without the user's say-so.
- **Own retries.** 3 attempts with backoff, SDK `max_retries=0`, timeout 600 s.
- **No numeric aggregate risk estimates** in answers (system prompt rule 11; revisit in phase 2).
- **A prompt change applies to all configs** and triggers a rerun of the affected eval stage (phase 2).
- **Synthetic data only.**

## Provider notes

- **Anthropic** (Messages API): `output_config` with effort and json_schema format; `cache_control` on the record block; stream and use `.get_final_message()`; thinking is always on for Opus 5.5 and Fable 5.1.
- **OpenAI** (Responses API): `reasoning.effort`, `max_output_tokens`, strict json_schema, automatic prefix caching, `store=False`.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pytest                                   # offline
thalamus show-record
thalamus ask "What was her most recent amniotic fluid index?"
thalamus export --format csv
streamlit run app.py                     # login: ajitesh / thalamus
```

## Before you finish a task

1. State which of the three intents it serves.
2. Run `pytest`; report failures with output.
3. Update the checklist in `docs/PHASED_IMPLEMENTATION_PLAN.md` if a task or exit criterion changed. Keep open items open until verified.
4. Ask before anything outward-facing or hard to reverse: live API calls (they cost money), creating GCP resources (project `kado-care`), pushing, deploying.

## Open decisions (need the user)

- Deployment host: Compute Engine VM with persistent disk, Caddy and sslip.io (recommended), or Cloud Run with a GCS volume.
- How API keys reach Secret Manager. (The web login is hardcoded in `app.py`.)
- Live smoke calls: needs the user's API keys and approval.
