# GCP Cloud Function — Pub/Sub → `cloud_alert_hub`

A four-file Cloud Function (2nd gen) that subscribes to a Pub/Sub topic,
pipes every message through the `cloud_alert_hub` library (installed from
GitHub via `requirements.txt`), and posts to Slack.

This is the recommended entry-point if you're wiring **GCP Cloud Billing
Budgets** or **Cloud Monitoring alert policies** to Slack.

## Contents

```
examples/gcp-cloud-function/
├── main.py           ← 10 lines of code; imports the library
├── requirements.txt  ← pip install cloud_alert_hub from your GitHub fork
├── config.yaml       ← per-deployment overrides (channel, thresholds, toggles)
└── deploy.sh         ← one-command `gcloud functions deploy`
```

## End-to-end walkthrough (≈10 minutes)

This is exactly the flow used to deploy the production nonprod instance —
with every real identifier replaced by a placeholder.

### 1. Create / confirm GCP prerequisites

```bash
# Set to your own project ID
export PROJECT_ID=my-nonprod-project

# Enable the APIs once per project
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  eventarc.googleapis.com \
  pubsub.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="$PROJECT_ID"

# Create the Pub/Sub topic Cloud Billing will publish to
gcloud pubsub topics create billing-alerts-nonprod --project="$PROJECT_ID"

# Create the GCS bucket the Cloud Function will use for persistent dedup
# state. Without this, cold starts wipe in-memory dedup state and the same
# threshold re-fires every ~22 minutes for the rest of the billing month.
gsutil mb -l "${REGION:-us-central1}" \
  "gs://${PROJECT_ID}-alert-hub-state"

# Grant the Cloud Function's runtime service account write access. Cloud
# Functions 2nd gen defaults to the Compute Engine default SA — replace with
# a dedicated SA if you've created one.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gsutil iam ch \
  "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com:roles/storage.objectAdmin" \
  "gs://${PROJECT_ID}-alert-hub-state"
```

### 2. Create the Slack incoming webhook

If you don't already have one: [`api.slack.com/messaging/webhooks`](https://api.slack.com/messaging/webhooks).
Pick the channel that will receive alerts (e.g. `#alerts-finops`). Keep the
URL secret — it goes into a Cloud Function env var, not a git-tracked file.

### 3. Copy this folder to a deploy directory outside the repo

Keeping the deployable config out of the upstream repo means secrets and
real IDs never risk being pushed:

```bash
mkdir -p ~/cloud-alert-hub-deploys/nonprod-budget-alerts
cp examples/gcp-cloud-function/* ~/cloud-alert-hub-deploys/nonprod-budget-alerts/
cd ~/cloud-alert-hub-deploys/nonprod-budget-alerts
```

> Treat `~/cloud-alert-hub-deploys/` as a private deploy sandbox — put it in
> `.gitignore` or keep it entirely outside git.

### 4. Pin `requirements.txt` to a release tag

```text
cloud-alert-hub[gcp] @ git+https://github.com/<you>/cloud-alert-hub.git@v0.3.3
functions-framework>=3.5.0
```

The `[gcp]` extra pulls in `google-cloud-storage` so the function can write
its persistent dedup state to the GCS bucket created above. Without it cold
starts re-fire suppressed alerts.

Using `@main` is only good for rapid iteration — pin to a tag (`@v0.3.3`) or
a commit SHA for production deploys so redeploys are reproducible.

### 5. Edit `config.yaml` for your environment

The shipped defaults turn on `features.budget_alerts` only. Change the Slack
channel, threshold list, and display toggles to match your org. The
full schema is documented in [`../../config.example.yaml`](../../config.example.yaml).

Minimal per-deployment edits:

```yaml
app:
  name: cloud-alert-hub-nonprod
  environment: nonprod
  cloud: gcp

features:
  budget_alerts:
    enabled: true
    # mirror whatever thresholds you configure on the billing budget
    thresholds_percent: [50, 70, 90, 100, 110, 120, 130, 140, 150,
                         160, 170, 180, 190, 200, 210, 220, 230, 240,
                         250, 260, 270, 280, 290, 300]
    route: finops

notifications:
  slack:
    enabled: true
    webhook_url_env: SLACK_WEBHOOK_URL
    default_channel: "#alerts-finops"
    display:
      show_account: false        # hide the billing account ID
      show_project: true
      show_progress_bar: true

routing:
  routes:
    finops:
      slack_channel: "#alerts-finops"
      email_recipients: ["finops-oncall@example.com"]

# Persistent dedup state — replace YOUR-PROJECT with the bucket created in
# step 1. The library writes a small JSON object here; no other resources
# go in this bucket.
state:
  backend: gcs
  bucket: YOUR-PROJECT-alert-hub-state
  object_path: dedup-state.json
```

### 6. Deploy

```bash
export PROJECT_ID=my-nonprod-project
export REGION=us-central1
export FUNCTION_NAME=cloud-alert-hub-nonprod
export PUBSUB_TOPIC=billing-alerts-nonprod
export RUNTIME=python312
export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/XXX/YYY/ZZZ'

chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` wraps `gcloud functions deploy … --gen2 --trigger-topic`. It:

1. Uploads `main.py`, `config.yaml`, `requirements.txt` to Cloud Storage.
2. Builds a container via Cloud Build (pip-installs `cloud_alert_hub` from
   GitHub).
3. Provisions a Cloud Run service + Eventarc trigger bound to the Pub/Sub
   topic.
4. Sets `SLACK_WEBHOOK_URL` as a Cloud Function env var.

First deploy takes ~90 seconds; subsequent deploys are faster.

### 7. Attach your Cloud Billing budget

Cloud Console → **Billing** → **Budgets & alerts** → pick or create a budget →
**Manage notifications** → **Connect a Pub/Sub topic** → select
`billing-alerts-nonprod` in `$PROJECT_ID`.

The budget will now publish JSON to the topic whenever a configured threshold
is crossed, which the Cloud Function will consume and post to Slack.

Alternative producers that work out of the box:

| Source | How to wire it |
|--------|----------------|
| **Cloud Monitoring alert policy** | Create a Pub/Sub notification channel pointing to the same topic |
| **Your own Cloud Run service** | `gcloud pubsub topics publish billing-alerts-nonprod --message='{…}'` |
| **Eventarc trigger** (Audit Logs, GCS, Firestore, …) | Have Eventarc forward the event to the same Pub/Sub topic |

## How we tested it (smoke tests)

These are the exact commands used to validate the nonprod deployment. They
don't touch real billing data — they publish synthetic budget events to the
topic, which Cloud Billing itself never sees.

### Publish one event per severity

```bash
for frac in 0.50 0.90 1.20 2.10; do
  pct=$(python3 -c "print(int(round($frac*100)))")
  gcloud pubsub topics publish billing-alerts-nonprod \
    --project="$PROJECT_ID" \
    --attribute=billingAccountId=smoke-test,budgetId=smoke-test,schemaVersion=1.0 \
    --message="{\"budgetDisplayName\":\"smoke test (${pct}%)\",\
\"budgetAmount\":10000,\"costAmount\":$(python3 -c "print(10000*$frac)"),\
\"currencyCode\":\"USD\",\"alertThresholdExceeded\":$frac,\
\"costIntervalStart\":\"2026-04-01T00:00:00Z\",\
\"budgetAmountType\":\"SPECIFIED_AMOUNT\"}"
  sleep 2
done
```

You should see four messages in the Slack channel within ~20 seconds:
🟡 LOW · 🔶 MEDIUM · 🔴 HIGH · 🚨 CRITICAL. See
[`../../docs/SAMPLE_OUTPUT.md`](../../docs/SAMPLE_OUTPUT.md) for what each
one looks like rendered.

### Tail function logs

```bash
gcloud functions logs read cloud-alert-hub-nonprod \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --gen2 \
  --limit=50
```

Healthy log lines look like:

```
cloud_alert_hub: processed route=finops event_id=<uuid>
```

Errors (usually a bad webhook or missing env var) show up as:

```
Traceback (most recent call last):  …
cloud_alert_hub: failed route=finops event_id=<uuid>
```

Any delivery failure is written to the dead-letter path
(`/tmp/cloud-alert-hub-dead-letter.jsonl` by default) for post-mortem.

### Verify there's exactly one subscriber on the topic

After migrating from a legacy alerter, confirm the old function is gone:

```bash
gcloud pubsub topics list-subscriptions billing-alerts-nonprod --project="$PROJECT_ID"
```

Expected: one subscription named `eventarc-<region>-cloud-alert-hub-nonprod-…`.

### Dry-run locally before any deploy

```bash
python - <<'PY'
import base64, json, os
os.environ["DRY_RUN"] = "true"
os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/DUMMY/DUMMY/DUMMY"

from cloud_alert_hub import handle_gcp_pubsub

payload = {
  "budgetDisplayName": "dry-run",
  "budgetAmount": 10000, "costAmount": 12000, "currencyCode": "USD",
  "alertThresholdExceeded": 1.2,
  "costIntervalStart": "2026-04-01T00:00:00Z",
  "budgetAmountType": "SPECIFIED_AMOUNT"
}
env = {
  "message": {
    "data": base64.b64encode(json.dumps(payload).encode()).decode(),
    "attributes": {"billingAccountId":"smoke","project_id":"my-nonprod-project","environment":"nonprod"},
  }
}
print(json.dumps(handle_gcp_pubsub(env, config="./config.yaml"), indent=2, default=str))
PY
```

Status should be `processed`, route `finops`, and the `deliveries.slack`
entry marked `dry_run`.

## Running multiple features as separate functions

One deployment should own one responsibility. To add a security-audit
pipeline on top of the budget one:

```bash
mkdir ~/cloud-alert-hub-deploys/nonprod-security-audit
cp examples/gcp-cloud-function/* ~/cloud-alert-hub-deploys/nonprod-security-audit/
# …then in config.yaml: disable budget_alerts, enable security_audit …
export PUBSUB_TOPIC=security-audit-events
export FUNCTION_NAME=cloud-alert-hub-security
./deploy.sh
```

Each Cloud Function instance stays tiny, deploys independently, and has its
own dedupe window and routing.

## Troubleshooting

See [`../../docs/DEBUG_RUNBOOK.md`](../../docs/DEBUG_RUNBOOK.md).
