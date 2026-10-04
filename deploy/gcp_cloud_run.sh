#!/usr/bin/env bash
# Deploy the Thalamus CDS tester app to Cloud Run (project kado-care, asia-south1).
# Run from the repo root:  bash deploy/gcp_cloud_run.sh
# Needs: gcloud logged in, a local .env with ANTHROPIC_API_KEY, OPENAI_API_KEY, SUPABASE_URL.
# Idempotent: re-running adds a new secret version and redeploys.
set -euo pipefail

PROJECT=kado-care
REGION=asia-south1
SERVICE=thalamus-cds
SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
SUPABASE_KEY_SECRET=thalamus-supabase-service-role-key   # already exists (used by thalamus-chat)

set -a; source .env; set +a
: "${ANTHROPIC_API_KEY:?}" "${OPENAI_API_KEY:?}" "${SUPABASE_URL:?}"

put_secret() {  # name value
  if gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$2" | gcloud secrets versions add "$1" --project "$PROJECT" --data-file=- >/dev/null
  else
    printf '%s' "$2" | gcloud secrets create "$1" --project "$PROJECT" --data-file=- --replication-policy=automatic >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$1" --project "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null
}

put_secret cds-anthropic-api-key "$ANTHROPIC_API_KEY"
put_secret cds-openai-api-key "$OPENAI_API_KEY"
gcloud secrets add-iam-policy-binding "$SUPABASE_KEY_SECRET" --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null

# Public URL: the app's own login is the gate (decided with the owner, 2026-10-05).
# One instance + session affinity: Streamlit keeps session state in memory.
# Runs are stored in Supabase (thalamus_harness_runs), so the container needs no persistent disk.
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source . \
  --allow-unauthenticated --session-affinity \
  --min-instances 0 --max-instances 1 --cpu 1 --memory 1Gi --timeout 900 \
  --set-env-vars "SUPABASE_URL=$SUPABASE_URL,MODEL_SELECTION=blind,ENABLED_CONFIGS=opus-high,DATA_DIR=/tmp/data" \
  --set-secrets "ANTHROPIC_API_KEY=cds-anthropic-api-key:latest,OPENAI_API_KEY=cds-openai-api-key:latest,SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_KEY_SECRET:latest"

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)'
