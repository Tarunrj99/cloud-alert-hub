# Deploying on GCP

The recommended runtime is a **2nd-gen Cloud Function** subscribed to a
Pub/Sub topic. The example lives under
[`examples/gcp-cloud-function/`](../examples/gcp-cloud-function/); this doc
walks through deploying it end-to-end.

> **Before you start** — read the [Requirements](../README.md#requirements)
> section of the top-level README. You need the `gcloud` CLI, a GCP project
> with billing enabled, and a Slack webhook URL.

## Prerequisites

| Item | How to check / fix |
| ---- | ------------------ |
| `gcloud` CLI installed and logged in | `gcloud auth list` |
| A GCP project ID you can deploy to | `gcloud config set project <PROJECT_ID>` |
| Billing enabled on the project | Console → Billing, or `gcloud beta billing projects describe $PROJECT_ID` |
| Deployer identity has the roles below | `gcloud projects get-iam-policy $PROJECT_ID` |
| Public GitHub fork of this repo | Cloud Build runs `pip install git+https://…` from there |
| Slack incoming webhook URL | <https://api.slack.com/messaging/webhooks> |

**Required IAM roles** on the deployer identity (project-scoped):

- `roles/cloudfunctions.admin`
- `roles/run.admin`
- `roles/eventarc.admin`
- `roles/pubsub.admin`
- `roles/iam.serviceAccountUser` (to attach the default runtime service
  account)

If you're an **Owner** on the project, you already have all of these.

## 1. Enable APIs (one-time per project)

```bash
export PROJECT_ID=your-gcp-project
gcloud config set project "$PROJECT_ID"

gcloud services enable \
    cloudfunctions.googleapis.com \
    run.googleapis.com \
    eventarc.googleapis.com \
    pubsub.googleapis.com \
    cloudbuild.googleapis.com \
    logging.googleapis.com
```

## 2. Create (or pick) the Pub/Sub topic

```bash
gcloud pubsub topics create billing-alerts-nonprod
```

You'll attach GCP billing budgets (and optionally Cloud Monitoring alert
policies) to this topic later.

## 3. Create the dedup-state bucket (one-time per project)

Cloud Function instances are short-lived (~10–30 min between cold starts),
but Cloud Billing re-publishes the same threshold message every ~22 minutes
for the rest of the billing period. Without a persistent dedup store you'd
get hundreds of duplicate Slack alerts per month.

The library's `gcs` state backend writes a tiny JSON object (~few KB) to a
bucket you create here:

```bash
gsutil mb -l "$REGION" "gs://${PROJECT_ID}-alert-hub-state"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gsutil iam ch \
  "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com:roles/storage.objectAdmin" \
  "gs://${PROJECT_ID}-alert-hub-state"
```

> Already using a custom Cloud Function service account? Replace the
> `compute@developer.gserviceaccount.com` member above with that SA email.

This bucket holds *only* the dedup state file; nothing else gets written
there. It's safe to re-use across multiple Cloud Functions for the same
project — each one writes its own object key.

## 4. Copy the example and point at your repo

```bash
cp -r examples/gcp-cloud-function ~/my-alerting-function
cd ~/my-alerting-function
```

Edit `requirements.txt`:

```
cloud-alert-hub[gcp] @ git+https://github.com/Tarunrj99/cloud-alert-hub.git@v0.4.0
functions-framework>=3.5.0
```

The `[gcp]` extra installs `google-cloud-storage`, which the library uses
to write its dedup state to the bucket created in step 3.

Edit `config.yaml` — at minimum:

* `app.environment` / `app.cloud` tags for your deployment.
* `features.budget_alerts.enabled: true` (turn off anything you don't want).
* `routing.routes.finops.slack_channel` + `email_recipients`.
* `state.bucket` → set to the bucket you created in step 3
  (`${PROJECT_ID}-alert-hub-state`).

## 5. Deploy

```bash
export PROJECT_ID=your-gcp-project
export REGION=us-central1
export FUNCTION_NAME=cloud-alert-hub-nonprod
export PUBSUB_TOPIC=billing-alerts-nonprod
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
chmod +x deploy.sh && ./deploy.sh
```

Under the hood `deploy.sh` runs:

```bash
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 --region "$REGION" --project "$PROJECT_ID" \
  --runtime python312 --source . --entry-point alert_handler \
  --trigger-topic "$PUBSUB_TOPIC" \
  --set-env-vars "SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}"
```

## 6. Smoke test

```bash
gcloud pubsub topics publish "$PUBSUB_TOPIC" --message='{
  "kind": "budget",
  "severity": "high",
  "title": "Smoke test 100%",
  "summary": "Budget alert from CLI.",
  "project_id": "your-gcp-project",
  "environment": "nonprod",
  "labels": {"budget_name": "demo", "threshold_percent": "100"}
}'
```

Check:

* Slack channel for the formatted alert.
* Cloud Function logs (`gcloud functions logs read "$FUNCTION_NAME"`) for
  the `cloud_alert_hub:` status line.

## 7. Wire real producers

### Billing budgets

Cloud Billing → Budgets & alerts → **Manage notifications** → **Connect a
Pub/Sub topic** → select the same topic. The function now receives every
budget threshold breach.

### Cloud Monitoring alert policies

1. Monitoring → Alerting → **Notification channels** → add a
   **Pub/Sub** channel pointing at your topic.
2. Attach the channel to any policy you want to route through the function.

## 8. Separation of duties (optional)

Deploy the same code a second time, pointing at a different topic, with a
different `config.yaml` that enables only one feature:

```
examples/gcp-cloud-function/
  - config.yaml (budget_alerts only)    → cloud-alert-hub-billing  → topic: billing-alerts
examples/gcp-cloud-function/
  - config.yaml (security_audit only)   → cloud-alert-hub-security → topic: security-findings
```

Both functions pull the same GitHub tag; they just ship different configs.

## Operational checklist

| Item | Where |
| ---- | ----- |
| Function logs | `gcloud functions logs read FUNCTION_NAME` |
| Delivery metrics | Cloud Monitoring → Dashboards → Cloud Functions |
| Dead-letter file | inside the function's filesystem (ephemeral) — pipe to a Cloud Storage bucket if you need persistence |
| Rolling back | redeploy with a previous tag in `requirements.txt` |

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `pip` fails on deploy | `requirements.txt` points at a private repo | Make the repo public or install via a deploy token |
| Function deploys but never triggers | Pub/Sub trigger permission missing on Eventarc SA | Re-run `deploy.sh`; gcloud adds the bindings automatically on 2nd-gen |
| Function is invoked but no Slack message appears | `SLACK_WEBHOOK_URL` env var not set, or the channel in `config.yaml` is wrong | `gcloud functions describe $FUNCTION_NAME --gen2` → check env vars |
| Every alert is suppressed with `no_feature_claimed` | Payload `kind` doesn't match any enabled feature | Enable `app.debug_mode: true` and re-publish; the log shows the decided feature and reason |
| Duplicate Slack messages for the same event | Pub/Sub re-emits every ~22 min while a budget threshold is exceeded; dedup state lost on Cloud Function cold start | Set `state.backend: gcs` with `state.bucket: ${PROJECT_ID}-alert-hub-state` (see step 3); confirm `dedupe_window_seconds` is large enough to span a billing period (≥ 32 days for monthly budgets) |
| `pip install` fails resolving `google-cloud-storage` | Forgot the `[gcp]` extra in `requirements.txt` | Use `cloud-alert-hub[gcp] @ git+…` instead of plain `cloud-alert-hub @ git+…` |
| Function logs `403 Permission denied on bucket` | Cloud Function runtime SA missing `roles/storage.objectAdmin` on the dedup bucket | Re-run the `gsutil iam ch` command from step 3 with the correct SA email |
| `Permission denied on topic` during `deploy.sh` | Deployer missing `roles/pubsub.admin` | Grant it: `gcloud projects add-iam-policy-binding $PROJECT_ID --member=user:$USER_EMAIL --role=roles/pubsub.admin` |

## Next steps

- Turn on more features (SLO, security, infra) → [`FEATURES.md`](FEATURES.md).
- Audit / debug a running deployment → [`DEBUG_RUNBOOK.md`](DEBUG_RUNBOOK.md).
- Tune config for production → [`CONFIGURATION.md`](CONFIGURATION.md).
- Deploying to AWS too? → [`DEPLOY_AWS.md`](DEPLOY_AWS.md).
