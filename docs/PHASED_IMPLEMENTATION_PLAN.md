# Thalamus CDSS: Phased Implementation Plan

As of 2026-10-04.

## Summary

Thalamus answers a doctor's questions about one patient's longitudinal record. The build runs in three phases, and each phase starts only when the previous one meets its exit criteria:

| Phase | Goal | Main output | Rough duration |
| --- | --- | --- | --- |
| 1. Basic harness | Ask any model any question about one patient, verify citations, log everything, let testers use it | CLI + login-protected web app + run logs | ~1 week |
| 2. Model selection | Pick one model and effort level using evidence, not impressions | Chosen config + frozen system prompt v2 | ~2 weeks |
| 3. Determinism | Same intent gives the same answer, whatever the phrasing | Canonicalizer + answer cache + always-on flags | ~2 weeks |

Durations are estimates for one engineer. Doctor review time is the usual bottleneck, so phases 2 and 3 depend mostly on reviewer availability.

**Scope for all three phases:** one patient at a time, synthetic data only (patient 2744 plus a few extra synthetic records for scale checks), obstetrics and gynecology questions. Real patient data does not enter the system until after phase 3 and proper DPDP-compliant infrastructure exist.

**Intent:** every task in this plan must serve the three intents in `PRODUCT_INTENT.md`: clinically accurate, traceable, deterministic.

**Related documents:**

- Product intent: `PRODUCT_INTENT.md`
- HLD for phase 1: "Thalamus CDSS v1: Basic Harness HLD" (Claude Doc)
- Build prompt for phase 1: `thalamus_harness_claude_code_prompt.md`

---

## Phase 1: Basic harness

### Goal

A small program that takes one patient record and one question, sends both to a selectable model, checks every cited value against the record, and logs the full run. A login-protected web page lets testers ask any question and read the answer.

**Revised scope (2026-10-04):** phase 1 is the harness only: ask a question, send the prompt and patient context to the model, get the answer. The eval runner (`eval`) and in-app ratings were removed. A doctor reviews answers manually. Both move to phase 2, where they are needed for model comparison.

### What gets built

| Component | What it does |
| --- | --- |
| Record loader | Parses the patient export into clean data; drops synthetic-generator metadata |
| Serializer + header | Writes the record identically every time, with a row ID on every line and a computed header (ages, gestational-age anchors, meds, allergies) |
| System prompt v1 | House rules from the doctor's feedback plus three answer shapes (lookup, timeline, synthesis) |
| Model adapters | One interface for Anthropic and OpenAI; config picks model and effort; no fallbacks |
| Answer parser | Validates JSON output against the schema; one retry |
| Citation checker | Confirms every documented value appears in the row it cites; one regeneration on failure |
| Storage | SQLite for runs (ratings table removed; returns in phase 2 if needed) |
| CLI | `ask`, `show-record`, `export` (`eval` removed; returns in phase 2) |
| Web app | Streamlit page with static username and password, free-text questions, answers with citations and a verified/unverified badge, session history |
| Deployment | Dockerfile, env-based secrets, persistent volume, HTTPS host |

### Tasks

- [x] Set up repo; copy `patient_2744.txt` and the questions file into `data/`
- [x] Record loader + tests
- [x] Serializer and header + tests (GA anchors match the hand-calculated table)
- [x] Answer schema, parser and citation checker + tests (15 planted-error answers all flagged)
- [x] Prompt assembly and both adapters with mocked tests
- [ ] One live smoke call per provider; confirm returned model IDs match (open: `opus-high` done 2026-10-04, model ID matched, verified; OpenAI astra still to do)
- [x] Pipeline, storage, CLI `ask` and `show-record`
- [x] CLI `export` (`eval` dropped from phase 1)
- [x] Streamlit app with login, blind/choose mode, session history (ratings dropped from phase 1)
- [x] Dockerfile, `.env.example`, README (image built by Cloud Build on deploy, 2026-10-05; local Docker build not tested)
- [ ] Create separate API keys for the deployed app with provider-side spend caps
- [ ] Fill `configs/pricing.yaml` (open: Anthropic done 2026-10-04 from the official pricing page, incl. cache-write price; OpenAI `gpt-6-astra` still null, so astra cost shows "unknown")
- [x] Log `cache_write_tokens` (SQLite + Supabase column) and include cache writes in cost; cost hand-checked against a live run
- [x] Deployed to a host: Cloud Run chosen over a VM; runs persist in Supabase, so no volume is needed (see the Cloud Run item below). Open: share URL and credentials with testers
- [x] `SupabaseStore` and `thalamus_harness_runs` migration written, tested offline
- [x] Migration applied to Supabase project `ygovtjqzztschecrqufq` (2026-10-04); live write and read verified (run b15aecbd, no SQLite fallback used)
- [x] Deployed to Cloud Run (`thalamus-cds`, kado-care, asia-south1, 2026-10-05) at https://thalamus-cds-4hoqiixfyq-el.a.run.app; GCP deploy section in README. Public URL, gated only by the hardcoded app login; revision `thalamus-cds-00004-gbw` live, `/_stcore/health` 200 (2026-10-05); browser end-to-end test by the owner pending
- [x] Manual GitHub Action redeploy (`.github/workflows/deploy-cds.yml`); one-time `deploy/gcp_ci_setup.sh` run; Action run 37261871406 succeeded (2026-10-05)

### Exit criteria

- [x] All tests pass (81 passed, 2 live skipped)
- [x] Serializing patient 2744 ten times gives the same hash
- [ ] `thalamus ask` works live for all six configs, and every logged model ID matches the request (not yet run live)
- [x] Prompt cache hits appear in logged token counts (Anthropic verified 2026-10-04: 9,466 of 9,499 input tokens cached on calls within the 5-minute TTL, including with a different question; OpenAI still to check)
- [ ] Web app requires login, accepts any question, and keeps run data across restarts (login and logging tested; runs stored in Supabase; owner's browser test of the deployed app pending)
- [x] Deployed at an HTTPS URL (Cloud Run); persistence via Supabase instead of a volume

Removed from phase 1: `thalamus eval` on the 36 questions with `metrics.csv`, `grading.csv`, `key.csv`; saving ratings.

### Decisions already made

- Whole record in the prompt; no RAG, no vector database
- Code does all date and age arithmetic; the model never does
- Static, hardcoded login in `app.py` (decided 2026-10-04): username `ajitesh`, password `thalamus`. Not env vars. Acceptable only because the repo is private and the data is synthetic; replace with real auth before any real patient data. No question limits
- Blind mode is supported in the web app (`MODEL_SELECTION`), but only `opus-high` is enabled and it is the default model (changed from medium-effort configs enabled). Blinding has no effect until more than one config is enabled.
- No eval flow and no ratings in phase 1; a doctor reviews answers manually
- No aggregate numeric risk estimates (system prompt rule 11; revisit in phase 2)
- Host: Cloud Run (`thalamus-cds`, kado-care, asia-south1), public URL gated by the app login, one instance with session affinity, runs in Supabase (decided 2026-10-05)
- Prose names encounters in words, e.g. "Encounter 7 (inpatient visit, 2023-05-15)", never bare `E7` (system prompt rule 14, 2026-10-05). Serves traceable and readable; row IDs stay in `cites` and `rows`. Not yet checked on a live answer; applies to all configs, so phase 2 evals use this prompt

---

## Phase 2: Model selection

### Goal

Choose one model and effort level from six candidates, using the same harness and prompt for all of them, with a decision rule written down before any results come in.

### Candidates

| Config | Provider | Model | Effort |
| --- | --- | --- | --- |
| opus-medium | Anthropic | Claude Opus 5.5 | medium |
| opus-high | Anthropic | Claude Opus 5.5 | high |
| fable-medium | Anthropic | Claude Fable 5.1 | medium |
| fable-high | Anthropic | Claude Fable 5.1 | high |
| astra-medium | OpenAI | GPT-6 Astra | medium |
| astra-high | OpenAI | GPT-6 Astra | high |

Effort labels are not calibrated across providers, so configs are compared on cost against quality, not by label.

### Evaluation set

- **Patient 2744, all 36 questions**, each in 3 phrasings: clean, sloppy (abbreviations, typos, Hinglish) and vague.
- **2 long synthetic records (30k+ tokens)** with about 10 questions each. The product scope stays single-patient; these exist only to check that the chosen model holds up on realistic record lengths.
- **Answer key** for lookup and counting questions, written once by the doctor.
- **Tester questions** collected through the web app during phase 1 and 2, added to the set when useful.

### Tasks

- [ ] Fill the remaining `pricing.yaml` entries (OpenAI) from the provider pricing page (carried over from phase 1)
- [ ] Rebuild the eval runner removed from phase 1: run all questions across configs, write `metrics.csv`, `grading.csv` and `key.csv`
- [ ] Rebuild grading storage (ratings table) and a blinded grading view for the doctor
- [ ] Enable all six configs in the app (`ENABLED_CONFIGS`) so blind mode is meaningful
- [ ] Doctor writes answer keys for lookup and counting questions
- [ ] Write the 2 extra phrasings per question
- [ ] Build the 2 long synthetic records and their questions
- [ ] Write down the decision rule (below) and commit it before running anything
- [ ] Settle the open prompt decisions: numeric risk policy, whether to always mention benign alternatives (e.g. fetal sleep cycle on an NST question), word caps per answer shape
- [ ] **Stage 1, automated screen:** run all six configs on the full set; compare answer-key accuracy, verification pass rate, schema failure rate, format compliance, cost per answer and latency
- [ ] Cut to the top 2 or 3 configs
- [ ] **Stage 2, blinded clinical grading:** finalists answer the interpretation, conflict and synthesis questions; doctor grades blinded and randomized answers (correct, minor error, major error, unsafe, plus bedside preference)
- [ ] Second clinician grades a 20% overlap; adjudicate disagreements
- [ ] Apply the decision rule; record the choice and the evidence in the decisions log
- [ ] Freeze system prompt v2

### Prompt changes during phase 2

Any prompt change applies to all configs and triggers a full rerun of the affected stage. This stops the prompt from being tuned to one model's quirks.

### Decision rule (commit before running)

1. Any answer graded unsafe disqualifies a config, or sends it back for review.
2. Among the remaining configs, pick the cheapest one whose clinical score is within a pre-set margin (proposed: 5%) of the best.
3. If two configs are within noise, pick the faster or cheaper one. With roughly 150 graded judgments, differences of a few points are not meaningful.

### Exit criteria

- [ ] One config chosen and documented with its metrics
- [ ] Zero unsafe answers for the chosen config in stage 2
- [ ] System prompt v2 frozen
- [ ] Cost per answer known for the chosen config

---

## Phase 3: Determinism

### Goal

The same clinical intent gives the same answer regardless of phrasing or repeat. Determinism comes from the architecture (canonical questions plus caching), not from model settings.

### Definition

| Level | Meaning | How it is achieved |
| --- | --- | --- |
| Repeat-identical | The same question asked twice returns identical bytes | Answer cache |
| Paraphrase-identical | Different phrasings of the same intent return identical bytes | Canonicalizer + answer cache |
| Content-consistent | Questions that miss the cache still reach the same facts and conclusion | Policy rules in the system prompt |

### Tasks, in order, measuring after each step

- [ ] **Baseline:** with the chosen config, run each question 5 times and in 5 or more phrasings. Measure key-fact agreement, conclusion agreement and byte equality. This shows where variance actually comes from.
- [ ] **Policy rules:** for every question where answers diverged in phase 2 or the baseline (e.g. gestational age anchoring, SUI severity scale, numeric risk), write one rule into the system prompt. Rerun the baseline.
- [ ] **Canonicalizer:** one small LLM call maps any question to a canonical question from a fixed list (about 15 to 20 for this patient's question types), or to `other` with a rewritten canonical sentence. Constrained output only. Measure intent agreement across phrasings.
- [ ] **Answer cache:** key = (`record_hash`, `prompt_version`, `config_id`, canonical question). Invalidate when any part changes. Repeats and paraphrases of a cached intent return identical bytes.
- [ ] **Always-on flags block:** one patient-level block of critical findings, conflicts and overdue items, generated once per `record_hash` and shown above every answer, whatever was asked.
- [ ] **Canonical answer review:** the doctor reviews the cached answers for patient 2744's canonical questions, so a wrong first answer does not become a permanently cached wrong answer. Add an admin action to regenerate a cached answer.
- [ ] Update the web app: show whether an answer came from the cache and which canonical question it matched.

### Exit criteria (targets proposed, confirm before starting)

- [ ] Canonicalizer agreement of at least 95% across phrasings of the same intent
- [ ] 100% identical answers for cache hits, by construction
- [ ] Doctor-graded accuracy no lower than the phase 2 result
- [ ] Flags block shows every critical item in the answer key, for every question

### Known trade-off

Caching makes answers consistent, not correct. A wrong first answer stays wrong until regenerated. That is why canonical answer review is a required task, not an optional one.

---

## After phase 3 (not planned in detail)

- Multiple patients and a real database
- Ingestion of real records (EMR exports, FHIR, PDFs from Indian labs)
- DPDP-compliant hosting, access control and audit logging for real patient data
- Regulatory assessment for software as a medical device (CDSCO, and FDA if relevant)
- A proper doctor-facing UI
- Guideline retrieval, only if phase 2 shows standard-of-care claims are a frequent error source

## Cross-cutting

- **Decisions log:** every settled choice (model, prompt rules, thresholds) is written down with its evidence.
- **Cost tracking:** cost per answer is reported in every eval run and watched daily on the deployed app.
- **Data handling:** synthetic data only until real-data infrastructure exists.
- **Reproducibility:** every run is identified by record hash, prompt version, question and config.
