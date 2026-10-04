#!/usr/bin/env bash
# One-time IAM setup so .github/workflows/deploy-cds.yml can deploy via Workload Identity Federation.
# Creates a dedicated service account (cds-ci-sa) that only ajitesh13/cds-model-testing can impersonate.
# Run once from anywhere with gcloud logged in as a project owner:  bash deploy/gcp_ci_setup.sh
set -euo pipefail

PROJECT=kado-care
REGION=asia-south1
REPO=ajitesh13/cds-model-testing
SA_NAME=cds-ci-sa
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
RUNTIME_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"   # runs thalamus-cds
POOL="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool"
BUCKET="gs://$PROJECT-cds-build"

gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
       --display-name "Thalamus CDS CI deployer (GitHub Actions)"

# Project roles: same set thalamus-ci-sa uses, nothing more.
for role in roles/run.developer roles/cloudbuild.builds.editor roles/artifactregistry.writer roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$role" --condition=None >/dev/null
done

# Deploying a revision that runs as the runtime SA requires actAs on it.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/iam.serviceAccountUser >/dev/null

# Staging bucket for `gcloud builds submit`, owned outright by the CI account.
gcloud storage buckets describe "$BUCKET" --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location "$REGION" --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding "$BUCKET" --member "serviceAccount:$SA" --role roles/storage.admin >/dev/null

# Only this repo may impersonate the account (the provider itself only checks the owner).
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --member "principalSet://iam.googleapis.com/$POOL/attribute.repository/$REPO" \
  --role roles/iam.workloadIdentityUser >/dev/null

echo "Done. Trigger: GitHub -> Actions -> 'Deploy Thalamus CDS (Cloud Run)' -> Run workflow."
