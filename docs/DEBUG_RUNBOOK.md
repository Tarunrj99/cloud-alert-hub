# Debug runbook

A checklist for investigating why an alert didn't show up (or did show up
and shouldn't have).

## Quick turn-ons

| Flag | Where | Effect |
| ---- | ----- | ------ |
| `app.debug_mode: true` | `config.yaml` | Every response includes a `debug.trace` with the matched feature, dedupe key, chosen route, and target. |
| `app.dry_run: true` | `config.yaml` | Render and log, but don't deliver. Useful when iterating on rendering. |
| `DEBUG_MODE=true` env var | shell / cloud env | Overrides `app.debug_mode` without editing YAML. |
| `DRY_RUN=true` env var | shell / cloud env | Same for `app.dry_run`. |

## 1. Did the event reach the library?

### GCP

```bash
gcloud functions logs read $FUNCTION_NAME --limit 50
```

Look for the `cloud_alert_hub: …` print line. Its absence means the trigger
never fired (publisher → topic / subscription wiring is broken) or the
function crashed before logging.

### AWS

```bash
aws logs tail /aws/lambda/$FUNCTION_NAME --follow
```

Same story — no `cloud_alert_hub` entries means SNS isn't reaching the Lambda.

### Local

```bash
curl -sX POST http://127.0.0.1:8000/ingest/generic \
  -H 'content-type: application/json' \
  -d @examples/payloads/generic-budget-alert.json | jq
curl -s http://127.0.0.1:8000/debug/metrics | jq
```

## 2. What did the policy decide?

With `debug_mode: true`, the response payload (and the corresponding log
line) contains:

```json
{
  "status": "processed",
  "route_key": "finops",
  "deliveries": { ... },
  "debug": {
    "trace": {
      "incoming_kind": "budget",
      "enabled_features": ["budget_alerts", "security_audit"],
      "matched_feature": "budget_alerts",
      "route_key": "finops",
      "dedupe_key": "gcp:my-project:demo:100",
      "dedupe_window_seconds": 1800,
      "target": { "slack_enabled": true, "slack_channel": "#alerts", ... }
    }
  }
}
```

### Common reasons for `status: "suppressed"`

| `reason` | Fix |
| -------- | --- |
| `global_alerting_disabled` | Set `app.alerting_enabled: true` (or clear `ALERTING_ENABLED=false`). |
| `no_feature_claimed` | The alert's `kind` doesn't match any enabled feature. Fix the producer's `kind` field or turn on the feature. |
| `dedupe_window` | An identical alert (same dedupe key) arrived within `dedupe_window_seconds`. Wait or shorten the window for testing. |

## 3. Was Slack called?

Inside `deliveries.slack` you'll see one of:

| `status` | Meaning |
| -------- | ------- |
| `sent` | HTTP 2xx from Slack. |
| `failed` | Slack returned non-2xx; `status_code` is included. |
| `dry_run` | `app.dry_run` was true — nothing sent. |
| `skipped` | Webhook env var is empty. Set the `SLACK_WEBHOOK_URL` (or whatever `notifications.slack.webhook_url_env` points at). |
| `error` | Client-side exception (network, SSL, timeout). The exception message is included. |

If Slack returned 403 or 404, the webhook URL is wrong or disabled. If it
returned 429, you're rate-limited — the retry logic handles this, but
consider widening `delivery.retry_backoff_seconds`.

## 4. Was anything dead-lettered?

After all retries fail, the event lands in
`$DEAD_LETTER_FILE_PATH` (default `/tmp/alerting-dead-letter.jsonl`). For
Cloud Functions / Lambdas this directory is ephemeral — pipe it to a
bucket if you need durable audit evidence.

## 5. Metrics

The local dev server exposes counters at `/debug/metrics`:

```json
{
  "events_received_total": 12,
  "events_processed_total": 10,
  "events_suppressed_total": 2,
  "slack_attempt_total": 10,
  "slack_success_total": 9,
  "slack_failed_total": 1,
  "deliveries_success_total": 9,
  "deliveries_failed_total": 1
}
```

For Cloud Functions / Lambdas, export these to Cloud Monitoring or
CloudWatch by subclassing `MetricsTracker` and pushing to the provider's
custom-metrics API.

## 6. Reproducing production events locally

1. Copy the failing event from Cloud Function logs.
2. Save it to `examples/payloads/my-case.json`.
3. Run:

   ```bash
   curl -sX POST http://127.0.0.1:8000/ingest/gcp/pubsub \
     -H 'content-type: application/json' \
     -d @examples/payloads/my-case.json | jq
   ```

4. Inspect the `debug.trace` to understand the routing decision.

## 7. Smoke tests you can copy-paste

### GCP — all four severities

Publishes four synthetic budget events (one at each severity band) into a
Pub/Sub topic your Cloud Function already subscribes to. No real Cloud
Billing budget is touched.

```bash
PROJECT_ID="my-nonprod-project"
TOPIC="billing-alerts-nonprod"

for frac in 0.50 0.90 1.20 2.10; do
  pct=$(python3 -c "print(int(round($frac*100)))")
  gcloud pubsub topics publish "$TOPIC" --project="$PROJECT_ID" \
    --attribute=billingAccountId=smoke-test,budgetId=smoke-test,schemaVersion=1.0 \
    --message="{\"budgetDisplayName\":\"smoke test (${pct}%)\",\
\"budgetAmount\":10000,\"costAmount\":$(python3 -c "print(10000*$frac)"),\
\"currencyCode\":\"USD\",\"alertThresholdExceeded\":$frac,\
\"costIntervalStart\":\"2026-04-01T00:00:00Z\",\"budgetAmountType\":\"SPECIFIED_AMOUNT\"}"
  sleep 2
done

gcloud functions logs read cloud-alert-hub-nonprod \
  --project="$PROJECT_ID" --region=us-central1 --gen2 --limit=30
```

Expected: four `cloud_alert_hub: processed route=finops event_id=…` log lines
and four Slack messages (LOW / MEDIUM / HIGH / CRITICAL).

### GCP — monitoring incident (critical)

```bash
gcloud pubsub topics publish "$TOPIC" --project="$PROJECT_ID" \
  --message='{"version":"1.2","incident":{"incident_id":"demo","scoping_project_id":"my-nonprod-project","policy_name":"Error rate too high","condition_name":"5xx > 5%","state":"open","summary":"Error rate 12% for Cloud Run","url":"https://console.cloud.google.com/monitoring/alerting"}}'
```

### AWS — Lambda smoke

```bash
SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:alerts

aws sns publish --topic-arn "$SNS_TOPIC_ARN" \
  --message='{"kind":"budget","title":"AWS smoke 120%","summary":"test","severity":"high",
"labels":{"budget_name":"demo","threshold_percent":"120"}}'

aws logs tail /aws/lambda/cloud-alert-hub-nonprod --follow
```

### Local dev server

```bash
export INGEST_SHARED_TOKEN=dev-token          # or turn off ingress_auth
make run-server &
curl -sX POST http://127.0.0.1:8000/ingest/generic \
  -H 'content-type: application/json' \
  -H 'x-ingest-token: dev-token' \
  -d @examples/payloads/generic-budget-alert.json | jq
```

### Dry-run the whole pipeline in one shell

Useful before any real deploy to verify that your `config.yaml` + the library
produce the exact Slack layout you want:

```bash
python - <<'PY'
import base64, json, os
os.environ["DRY_RUN"] = "true"
os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/DUMMY/DUMMY/DUMMY"

from cloud_alert_hub import handle_gcp_pubsub

with open("examples/payloads/gcp-billing-budget-native.json") as f:
    envelope = json.load(f)

print(json.dumps(
    handle_gcp_pubsub(envelope, config="./config.yaml"),
    indent=2, default=str))
PY
```

## 8. Rolling back

1. Keep the previous tag reference in `requirements.txt` (e.g. `@v0.1.0`).
2. Redeploy — `gcloud functions deploy` creates a new revision; traffic
   switches atomically. If the new revision crashes on startup, Cloud Run
   keeps serving the previous revision.
3. If you must fully revert: rerun `deploy.sh` with the old tag pinned.

