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
