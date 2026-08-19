#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
KEY_FILE="${2:-aidy-bigquery-exporter-key.json}"
SERVICE_ACCOUNT_ID="aidy-bigquery-exporter"

if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "Usage: $0 GOOGLE_CLOUD_PROJECT_ID [KEY_OUTPUT_FILE]" >&2
  exit 2
fi

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Configuring AIDY Day 4 BigQuery access in project: ${PROJECT_ID}"
gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable bigquery.googleapis.com iam.googleapis.com --project="$PROJECT_ID"

if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" \
  --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SERVICE_ACCOUNT_ID" \
    --project="$PROJECT_ID" \
    --display-name="AIDY BigQuery Exporter"
fi

# BigQuery User is sufficient at project level for this bootstrap: it can create
# datasets and run jobs. BigQuery makes the dataset creator Data Owner on the
# dataset it creates, so no project-wide BigQuery Admin/Data Owner is required.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/bigquery.user" \
  --condition=None \
  --quiet >/dev/null

umask 077
if [[ -e "$KEY_FILE" ]]; then
  echo "Refusing to overwrite existing key file: ${KEY_FILE}" >&2
  exit 3
fi

gcloud iam service-accounts keys create "$KEY_FILE" \
  --iam-account="$SERVICE_ACCOUNT_EMAIL" \
  --project="$PROJECT_ID"

cat <<EOF

AIDY Day 4 Google Cloud bootstrap complete.

Service account: ${SERVICE_ACCOUNT_EMAIL}
Key file:        ${KEY_FILE}

NEXT OWNER ACTION
1. Open GitHub repository dannythehat/Aidy-Gold-Signals.
2. Settings -> Secrets and variables -> Actions -> New repository secret.
3. Name it exactly: AIDY_GCP_SERVICE_ACCOUNT_JSON
4. Paste the COMPLETE contents of ${KEY_FILE} as the secret value.
5. Delete the local key file after the secret is stored securely.

Do not paste this key into chat, Notion, source code, issues, PR comments, or commits.
The Day 4 workflow derives the Google Cloud project ID from the JSON itself; no separate project-ID secret is required.
EOF
