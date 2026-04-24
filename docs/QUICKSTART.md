# Quickstart

Five minutes from zero to a Slack-posting alert pipeline.

## 0. Prerequisites

* A public GitHub fork of this repo (you'll point `pip install` at it).
* A target cloud account (GCP or AWS) with permission to create functions
  and pub/sub topics / SNS topics.
* A Slack incoming webhook URL. Create one at
  https://api.slack.com/messaging/webhooks if you don't already have one.

## 1. Pick your runtime

| Runtime | Folder | Event source | Best for |
| ------- | ------ | ------------ | -------- |
| GCP Cloud Function (2nd gen) | [`examples/gcp-cloud-function/`](../examples/gcp-cloud-function/) | Pub/Sub | GCP billing, monitoring |
| AWS Lambda | [`examples/aws-lambda/`](../examples/aws-lambda/) | SNS | AWS budgets, CloudWatch |
| Local FastAPI server | [`examples/local-dev/`](../examples/local-dev/) | HTTP | Development only |

## 2. Copy the example folder

```bash
cp -r examples/gcp-cloud-function ~/projects/my-alerting-function
cd ~/projects/my-alerting-function
```

## 3. Point the library at *your* GitHub fork

Edit `requirements.txt`:

```text
git+https://github.com/Tarunrj99/cloud-alert-hub.git@main#egg=cloud-alert-hub
functions-framework>=3.5.0
```

Pin to a tag (`@v0.1.0`) once you're happy with a release.

## 4. Edit `config.yaml`

Turn on the feature you want, plug in your Slack channel and recipients. The
rest is inherited from the bundled defaults.

```yaml
features:
  budget_alerts:
    enabled: true
    thresholds_percent: [50, 70, 90, 100, 120, 150, 200]
routing:
  routes:
    finops:
      slack_channel: "#GCP-Alerts-Nonprod"
      email_recipients: ["tarun.saini@example.com"]
```

## 5. Deploy

### GCP

```bash
export PROJECT_ID=your-gcp-project
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
export PUBSUB_TOPIC=billing-alerts-nonprod
./deploy.sh
```

### AWS

```bash
export ROLE_ARN=arn:aws:iam::123456789012:role/cloud-alert-hub-lambda
export SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:alerts
export SLACK_WEBHOOK_URL=...
./deploy.sh
```

## 6. Test

Publish a test message:

```bash
# GCP
gcloud pubsub topics publish billing-alerts-nonprod \
  --message='{"kind":"budget","title":"Test 100%","summary":"dry run","labels":{"threshold_percent":"100"}}'

# AWS
aws sns publish --topic-arn $SNS_TOPIC_ARN \
  --message='{"kind":"budget","title":"Test 100%","summary":"dry run","labels":{"threshold_percent":"100"}}'
```

You should see a formatted alert in Slack within seconds. Check the function
logs for the `cloud_alert_hub:` line that lists status and route.

## 7. Wire your real producer

### GCP billing budgets

Cloud Billing → Budgets → **Manage notifications** → **Connect a Pub/Sub
topic** → pick the topic your Cloud Function listens on.

### GCP Cloud Monitoring alert policies

Create a **Pub/Sub notification channel** pointing to the same topic, then
attach it to any alert policy.

### AWS Budgets

Budget actions → SNS topic → the SNS topic your Lambda is subscribed to.

### AWS CloudWatch alarms

Alarm action → SNS topic.

Anything that can publish JSON to SNS / Pub/Sub can drive `cloud_alert_hub`.

## Next

* Learn what each config key does → [`CONFIGURATION.md`](CONFIGURATION.md).
* Turn on more features → [`FEATURES.md`](FEATURES.md).
* Troubleshoot → [`DEBUG_RUNBOOK.md`](DEBUG_RUNBOOK.md).
