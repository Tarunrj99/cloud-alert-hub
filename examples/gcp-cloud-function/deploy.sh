#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Deploy the Cloud Function (2nd gen) that fronts a Pub/Sub topic and calls
# cloud_alert_hub. Run from this directory.
#
# Edit the variables below, make sure `gcloud auth login` has the right
# identity, then:
#     chmod +x deploy.sh && ./deploy.sh
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID env var}"
REGION="${REGION:-us-central1}"
FUNCTION_NAME="${FUNCTION_NAME:-cloud-alert-hub-nonprod}"
PUBSUB_TOPIC="${PUBSUB_TOPIC:-billing-alerts-nonprod}"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:?set SLACK_WEBHOOK_URL env var}"
RUNTIME="${RUNTIME:-python312}"

echo "==> Deploying $FUNCTION_NAME to project $PROJECT_ID ($REGION)"

gcloud functions deploy "$FUNCTION_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --runtime "$RUNTIME" \
  --gen2 \
  --source . \
  --entry-point alert_handler \
  --trigger-topic "$PUBSUB_TOPIC" \
  --set-env-vars "SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}" \
  --memory 256Mi \
  --timeout 60s

echo "==> Deployed. Test with:"
echo "    gcloud pubsub topics publish $PUBSUB_TOPIC \\"
echo "        --message='{\"budgetDisplayName\":\"demo\",\"alertThresholdExceeded\":0.5,\"costAmount\":5000,\"budgetAmount\":10000}'"
