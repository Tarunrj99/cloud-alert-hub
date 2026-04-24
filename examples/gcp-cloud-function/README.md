# GCP Cloud Function — Pub/Sub → cloud_alert_hub

A four-file Cloud Function (2nd gen) that subscribes to a Pub/Sub topic,
passes every message to the `cloud_alert_hub` library installed from GitHub, and
posts to Slack.

```
examples/gcp-cloud-function/
├── main.py            <-- 10 lines of code, imports the library
├── requirements.txt   <-- pip install cloud_alert_hub from your public repo
├── config.yaml        <-- your overrides (routes, thresholds, …)
└── deploy.sh          <-- one-command `gcloud functions deploy`
```

## 1. Prepare

```bash
# Enable APIs once per project
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
    eventarc.googleapis.com pubsub.googleapis.com

# Create the topic your billing budget (or any other source) will publish to
gcloud pubsub topics create billing-alerts-nonprod
```

## 2. Point `requirements.txt` at your repo

Edit the `git+https://...` line in `requirements.txt` so it points to your
fork of this project. Pin to a tag (`@v0.1.0`) for reproducible deploys.

## 3. Tweak `config.yaml`

The shipped example enables only `features.budget_alerts`. Enable more
features (service SLO, security, infra) or change routing exactly the same
way — one file, one section per feature.

## 4. Deploy

```bash
export PROJECT_ID=your-gcp-project
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
./deploy.sh
```

## 5. Hook up a producer

Any Pub/Sub publisher works. For GCP billing budgets:

```
Budget → Manage notifications → Connect a Pub/Sub topic → billing-alerts-nonprod
```

For Cloud Monitoring alert policies:

```
Notification channel (Pub/Sub) → billing-alerts-nonprod
```

Both will push into the same Cloud Function; the `kind` field on the payload
decides which feature handles it.

## Running multiple features as separate functions

Deploy the same code a second time with a different `config.yaml` and
different `FUNCTION_NAME` / `PUBSUB_TOPIC` — e.g. `cloud-alert-hub-security` with
only `features.security_audit.enabled = true`. The GitHub codebase stays
unchanged; the config file is the only thing that differs per deployment.
