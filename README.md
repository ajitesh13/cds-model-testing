# Thalamus CDSS phase 1

Test bench for a clinical decision support assistant (obstetrics and gynecology). The whole serialized patient
record plus one question goes to a selectable LLM; citations in the answer are checked against the record by
deterministic code; every run is logged to SQLite; testers grade answers in a login-protected web page.

Plain Python. The only non-deterministic step is the single model call (plus at most one schema retry and
one citation retry). No fallback models are ever configured.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
set -a; source .env; set +a      # ANTHROPIC_API_KEY / OPENAI_API_KEY etc. Never commit .env
pytest                            # offline; live smoke tests need RUN_LIVE=1

thalamus show-record
thalamus ask "What was her most recent amniotic fluid index?"            # default config: opus-high
thalamus ask --config astra-medium "Has she ever had a miscarriage?"
thalamus eval --configs opus-high,fable-high --concurrency 4              # -> var/evals/<timestamp>/
thalamus eval --out var/evals/<existing-dir>                              # resume an interrupted eval
thalamus export --format csv

APP_USERNAME=me APP_PASSWORD=pw streamlit run app.py
```

Configs live in `configs/models.yaml` (default: `opus-high`). Fill `configs/pricing.yaml` from the provider
pricing pages; until then cost is shown as "unknown".

### Environment variables

| Name | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Provider keys (environment only) |
| `APP_USERNAME`, `APP_PASSWORD` | Web login. The app refuses to start if either is unset |
| `DATA_DIR` | Where `thalamus.db` and `evals/` live (default `./var`, `/data` in Docker) |
| `MODEL_SELECTION` | `blind` (default; random config per question, model hidden) or `choose` |
| `ENABLED_CONFIGS` | Comma-separated config ids the web app may use (default: the YAML default) |

## Eval outputs

`var/evals/<timestamp>/`: `runs.jsonl`, `metrics.csv`, `grading.csv` (blinded, random answer IDs),
`key.csv` (answer ID to config). Answer-key accuracy is computed only for questions whose `answer_key` is set in
`data/questions_2744.yaml`.

## Deployment notes

- Serve only over HTTPS: the login form sends credentials.
- Use separate API keys for the deployed app, with provider-side spend caps.
- Keep the URL unlisted. There is one shared login and no rate limiting beyond a 1 s delay on a failed login.
- `DATA_DIR` must be on a persistent disk. SQLite needs real file locking, so mount a persistent disk at `/data`.
