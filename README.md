# Thalamus CDSS phase 1

Test bench for a clinical decision support assistant (obstetrics and gynecology). The whole serialized patient
record plus one question goes to a selectable LLM; citations in the answer are checked against the record by
deterministic code; every run is logged to SQLite; testers ask questions in a login-protected web page and a doctor reviews the answers by hand.

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
thalamus export --format csv                                             # dumps all logged runs

streamlit run app.py                                                     # login: ajitesh / thalamus (hardcoded in app.py)
```

Configs live in `configs/models.yaml` (default: `opus-high`). `configs/pricing.yaml` holds prices (Anthropic filled from the
official pricing page; OpenAI still null, so astra cost is shown as "unknown").

### Environment variables

| Name | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Provider keys (environment only) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Optional. When both are set, runs go to Supabase table `thalamus_harness_runs` (migration in `supabase/migrations/`). A failed write falls back to local SQLite, so no run is lost |
| `DATA_DIR` | Where `thalamus.db` lives (default `./var`, `/data` in Docker) |
| `MODEL_SELECTION` | `blind` (default; random config per question, model hidden) or `choose` |
| `ENABLED_CONFIGS` | Comma-separated config ids the web app may use (default: the YAML default) |

## Deployment notes

- Serve only over HTTPS: the login form sends credentials.
- Use separate API keys for the deployed app, with provider-side spend caps.
- The web login is hardcoded in `app.py` (username `ajitesh`, password `thalamus`); it is in the repo, so keep the repo private and the data synthetic. Keep the URL unlisted. There is one shared login and no rate limiting beyond a 1 s delay on a failed login.
- With Supabase configured the app is stateless and needs no persistent disk. Without it, `DATA_DIR` must be on a persistent disk. SQLite needs real file locking, so mount a persistent disk at `/data`.
