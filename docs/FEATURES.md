# Features

A **feature** is a self-contained alerting scenario. Each one:

* lives in a single file under [`src/cloud_alert_hub/features/`](../src/cloud_alert_hub/features/);
* claims incoming alerts by `kind`;
* picks its own route, severity, and dedupe key.

Features are toggled in `config.yaml`:

```yaml
features:
  budget_alerts:        { enabled: true }
  service_slo:          { enabled: false }
  security_audit:       { enabled: true }
  infrastructure_spike: { enabled: false }
```

## Built-in features

### `budget_alerts` — cost / budget threshold breaches

* **Claims when:** `alert.kind == "budget"`.
* **Expects on the payload:**
  * `labels.budget_name` — identifier the producer uses for the budget.
  * `labels.threshold_percent` — e.g. `"50"`, `"100"`, `"150"`.
  * `labels.cost_interval_start` — billing period start (ISO timestamp);
    the GCP adapter populates this from `costIntervalStart`. Used to make
    the dedupe key period-aware.
  * `metrics.cost_amount`, `metrics.budget_amount` (optional but nice).
* **Dedupe key:**
  `cloud:project:budget_name:cost_interval_start:threshold_percent`.
  This means each (budget × billing month × threshold) triple fires
  **exactly once** per `dedupe_window_seconds`. Because the period is in
  the key, an old 300% suppression in April will not block a fresh 50%
  alert in May.
* **Severity:** derived from the threshold (≥200% = critical, ≥100% = high,
  ≥90% = medium, else low).
* **Note:** the library does **not** send the cloud-native budget email.
  Those go directly from your cloud provider (`noreply-monitoring@google.com`
  for GCP, `no-reply@aws.amazon.com` for AWS Budgets, etc.) via the
  budget rule's notification channels and are *edge-triggered* — one
  email per fresh threshold crossing. The library only owns the Slack
  delivery (and an optional custom email via SES/SendGrid/SMTP).
* **Config:**
  ```yaml
  features.budget_alerts:
    enabled: true
    thresholds_percent: [50, 70, 90, 100, 110, 120, 150, 200, 300]
    dedupe_window_seconds: 2764800   # 32 days — covers a full billing month
    route: finops
  ```

### `service_slo` — error-rate / latency breaches

* **Claims when:** `alert.kind == "service"`.
* **Expects on the payload:**
  * `service` set to the service name.
  * `labels.incident_key` or `labels.policy_id` (whichever your monitoring
    provider gives you).
  * `metrics.error_rate_percent` and/or `metrics.latency_p95_ms`.
* **Dedupe key:** `cloud:service:incident_key`.
* **Config:**
  ```yaml
  features.service_slo:
    enabled: true
    error_rate_percent_gte: 3
    latency_p95_ms_gte: 500
    dedupe_window_seconds: 900
    route: sre
  ```

### `security_audit` — IAM / policy / config drift

* **Claims when:** `alert.kind == "security"`.
* **Expects on the payload:**
  * `labels.resource` (e.g. `iam-role/admin`).
  * `labels.action` (e.g. `role_binding_added`).
  * `labels.principal` (who performed the action).
* **Dedupe key:** `cloud:project:resource:action:principal`.
* **Config:**
  ```yaml
  features.security_audit:
    enabled: true
    dedupe_window_seconds: 300
    route: security
  ```

### `infrastructure_spike` — CPU / memory / disk / network

* **Claims when:** `alert.kind == "infrastructure"`.
* **Expects on the payload:**
  * `labels.metric` (e.g. `cpu_utilization`).
  * `labels.threshold` (e.g. `80`).
* **Dedupe key:** `cloud:project:metric:threshold`.
* **Config:**
  ```yaml
  features.infrastructure_spike:
    enabled: true
    dedupe_window_seconds: 600
    route: sre
  ```

## Adding a new feature

```python
# src/cloud_alert_hub/features/capacity.py
from ..models import CanonicalAlert
from .base import Feature, FeatureMatch


class CapacityFeature(Feature):
    name = "capacity"

    def claims(self, alert: CanonicalAlert) -> bool:
        return alert.kind == "capacity"

    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        return FeatureMatch(
            feature_name=self.name,
            route_key=self.route_key,
            severity=alert.severity or "medium",
            labels={"category": "capacity"},
            dedupe_key=f"{alert.cloud}:{alert.project}:{alert.labels.get('quota', 'unknown')}",
            dedupe_window_seconds=self.dedupe_window_seconds,
        )
```

Then:

1. Import and append to `FEATURE_CLASSES` in
   [`src/cloud_alert_hub/features/__init__.py`](../src/cloud_alert_hub/features/__init__.py).
2. Add a block to
   [`bundled_defaults.yaml`](../src/cloud_alert_hub/bundled_defaults.yaml):

   ```yaml
   features:
     capacity:
       enabled: false
       dedupe_window_seconds: 600
       route: sre
   ```

That's it. Existing deployments are unaffected until they set
`features.capacity.enabled: true` in their own `config.yaml`.

## Feature execution order

`load_enabled_features` preserves the order of `FEATURE_CLASSES`. The first
feature whose `claims()` returns `True` wins. If no feature claims the event,
the policy engine returns a `suppressed` result with `reason:
no_feature_claimed` (visible in the response `debug.trace` and in
`/debug/metrics`).

If two features could legitimately match the same `kind`, differentiate them
by using additional label checks inside `claims()`.
