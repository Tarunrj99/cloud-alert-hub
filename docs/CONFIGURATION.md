# Configuration reference

Every deployment is driven by **one** file (`config.yaml`). The library
deep-merges it on top of [`bundled_defaults.yaml`](../src/cloud_alert_hub/bundled_defaults.yaml) at
startup, so your file only needs to contain the keys you want to override.

A fully-annotated sample is at [`config.example.yaml`](../config.example.yaml).
This page is the authoritative reference for every key.

## Resolution order

1. `bundled_defaults.yaml` (shipped with the package).
2. Your `config.yaml` (dict, YAML file, or YAML string passed to `load_config`).
3. Selected environment variables (see the table under [`app.*`](#app)).

Later layers override earlier ones. Dicts merge recursively; lists replace.

## `app`

| Key | Type | Default | Env override | Notes |
| --- | ---- | ------- | ------------ | ----- |
| `app.name` | string | `cloud-alert-hub` | — | Cosmetic only; appears in logs. |
| `app.environment` | string | `unknown` | `APP_ENV` | Tag that ends up on every alert payload. Free-form. |
| `app.cloud` | string | `unknown` | `APP_CLOUD` | Primary cloud for this deployment. Free-form. |
| `app.alerting_enabled` | bool | `true` | `ALERTING_ENABLED` | Global kill-switch. Every event is suppressed when false. |
| `app.dry_run` | bool | `false` | `DRY_RUN` | Render + log, but don't actually deliver. |
| `app.debug_mode` | bool | `false` | `DEBUG_MODE` | Include policy trace in responses (verbose). |

## `features`

Each block toggles a scenario. If a key is present in `bundled_defaults.yaml`
but absent here, the default is used.

| Key | Notes |
| --- | ----- |
| `features.<name>.enabled` | `false` by default. Flip on to activate. |
| `features.<name>.route` | Which entry in `routing.routes` receives this feature's alerts. |
| `features.<name>.dedupe_window_seconds` | Minimum gap between alerts with the same dedupe key. |
| `features.budget_alerts.thresholds_percent` | Array of thresholds your producer will send as `labels.threshold_percent`. |
| `features.service_slo.error_rate_percent_gte` | Minimum error rate to count as a breach (evaluated against `alert.metrics.error_rate_percent`). |
| `features.service_slo.latency_p95_ms_gte` | Minimum p95 latency to count as a breach. |

See [`FEATURES.md`](FEATURES.md) for what each feature expects on the payload.

## `notifications`

### Slack

| Key | Default | Notes |
| --- | ------- | ----- |
| `notifications.slack.enabled` | `false` | |
| `notifications.slack.webhook_url_env` | `SLACK_WEBHOOK_URL` | Name of the env var holding the webhook. Never commit the webhook itself. |
| `notifications.slack.default_channel` | `#alerts` | Used when a route doesn't specify its own channel. |

### Email

| Key | Default | Notes |
| --- | ------- | ----- |
| `notifications.email.enabled` | `false` | |
| `notifications.email.provider` | `stdout` | `stdout \| smtp \| ses \| sendgrid` — only `stdout` ships built in; the others are easy to add in `notifiers/email.py`. |
| `notifications.email.from_address` | `alerts@example.com` | |
| `notifications.email.smtp_*` | — | Env var names for SMTP host / user / password. |

## `routing`

Named destinations. Features pick one by name; payloads can also override
via `route_key` if `payload_overrides.allowed_keys` includes it.

```yaml
routing:
  default_route: finops
  routes:
    finops:
      slack_channel: "#finops"
      email_recipients: [ "fin@example.com" ]
    sre:
      slack_channel: "#sre"
      email_recipients: []
    security:
      slack_channel: "#sec"
      email_recipients: [ "secops@example.com" ]
```

| Key | Default | Notes |
| --- | ------- | ----- |
| `routing.default_route` | `finops` | Used when nothing else matches. |
| `routing.routes.<name>.slack_channel` | — | Overrides `notifications.slack.default_channel`. |
| `routing.routes.<name>.email_recipients` | `[]` | Route is not emailed if empty. |

## `delivery`

| Key | Default | Notes |
| --- | ------- | ----- |
| `delivery.max_retries` | `3` | Total attempts = `max_retries + 1`. |
| `delivery.retry_backoff_seconds` | `[2, 5, 10]` | Per-attempt sleep; last value reused if there are more retries than entries. |
| `delivery.timeout_seconds` | `8` | Per-attempt HTTP timeout. |

After all retries fail, the event is written to the dead-letter file
(`DEAD_LETTER_FILE_PATH`, default `/tmp/alerting-dead-letter.jsonl`).

## `state`

| Key | Default | Env override | Notes |
| --- | ------- | ------------ | ----- |
| `state.backend` | `memory` | `STATE_BACKEND` | `memory \| file`. Use `memory` for short-lived Functions/Lambdas. |
| `state.file_path` | `/tmp/cloud-alert-hub-dedupe.json` | `STATE_FILE_PATH` | Only used when `backend: file`. |

## `payload_overrides`

```yaml
payload_overrides:
  enabled: true
  allowed_keys: [route_key, labels, annotations, mute_key, dedupe_key]
```

If `enabled` is true and the incoming event has an `overrides` dict, any
key in `allowed_keys` is copied onto the canonical alert. Keep this list
tight — it's the only way an untrusted producer can influence routing.

## `ingress_auth`

Only relevant for the FastAPI dev server (`examples/local-dev/app.py`).
Cloud Function / Lambda deployments rely on cloud IAM instead.

| Key | Default | Notes |
| --- | ------- | ----- |
| `ingress_auth.enabled` | `false` | |
| `ingress_auth.shared_token_env` | `INGEST_SHARED_TOKEN` | Env var holding the expected token. |

## Environment variables summary

| Variable | Overrides |
| -------- | --------- |
| `APP_ENV` | `app.environment` |
| `APP_CLOUD` | `app.cloud` |
| `ALERTING_ENABLED` | `app.alerting_enabled` |
| `DRY_RUN` | `app.dry_run` |
| `DEBUG_MODE` | `app.debug_mode` |
| `DEFAULT_ROUTE` | `routing.default_route` |
| `STATE_BACKEND` | `state.backend` |
| `STATE_FILE_PATH` | `state.file_path` |
| `SLACK_WEBHOOK_URL` (or whatever `notifications.slack.webhook_url_env` names) | Slack webhook value |
| `INGEST_SHARED_TOKEN` (or whatever `ingress_auth.shared_token_env` names) | Dev server auth token |
| `DEAD_LETTER_FILE_PATH` | Path for dead-letter .jsonl file |
