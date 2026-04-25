# Scenarios catalog

Catalog of what each built-in feature covers and which real-world signals
it's designed for. Use this when deciding which features to enable in a new
deployment.

## Cost / budget — `budget_alerts`

Fires on cloud billing threshold breaches.

| Cloud | Source → Pub/Sub / SNS → cloud_alert_hub |
| ----- | ------------------------------------ |
| GCP   | Cloud Billing Budget → Pub/Sub topic (user-selected) |
| AWS   | AWS Budgets → SNS topic |
| Azure | Cost Management → Action Group → webhook / Event Grid |

Typical thresholds to trip: 50, 70, 90, 100, 110, 120, 150, 200, 300
(percentage of the budget). Dedupe window should be longer than your
billing update cadence (GCP Cloud Billing publishes up to every 30 min, so
1800s is safe).

## Cost / usage spikes — `cost_spike`

Fires when a service's spend or usage in a given window jumps
significantly compared to its recent baseline. **Independent** from
`budget_alerts`: budgets are level-triggered (cumulative spend crossed
a step), spikes are delta-triggered (something broke today). Both are
useful and orthogonal.

| Cloud | Source → cloud_alert_hub                                                |
| ----- | ----------------------------------------------------------------------- |
| GCP   | Cloud Monitoring policy on `serviceruntime.googleapis.com/api/request_count` → Pub/Sub (with `kind=cost_spike` channel label) |
| GCP   | BigQuery scheduled query on the Cloud Billing export → Pub/Sub          |
| AWS   | Cost Explorer Cost Anomaly Detection → SNS (`kind=cost_spike` attr)     |
| Azure | Cost Management anomaly alert → Action Group webhook                    |
| any   | Custom detector → POST `/ingest/generic`                                |

End-to-end recipes for each path live in [`RECIPES.md`](./RECIPES.md).
The April 2026 Gemini-key abuse on the reference deployment would have
been caught by the GCP recipe within an hour.

The dedupe key is `cloud:project:service:spike_period`, so each
(service × period) fires exactly once. Default window: 1 day. Use
`service_allowlist` / `service_denylist` to scope.

## Reliability — `service_slo`

Fires when a service breaches an error-rate or latency SLO.

| Cloud | Source |
| ----- | ------ |
| GCP   | Cloud Monitoring alert policy (MQL or custom metric) → Pub/Sub channel |
| AWS   | CloudWatch alarm → SNS |
| Azure | Azure Monitor metric alert → Action Group |

Payload should include `metrics.error_rate_percent` and/or
`metrics.latency_p95_ms` so the feature can compare them to the thresholds
you configured.

## Security / governance — `security_audit`

Fires on IAM / policy / config changes an auditor would care about.

| Cloud | Source |
| ----- | ------ |
| GCP   | Security Command Center findings → Pub/Sub |
| GCP   | Audit logs (admin activity) → log sink → Pub/Sub |
| AWS   | Security Hub / GuardDuty → EventBridge → SNS |
| AWS   | CloudTrail event → EventBridge → SNS |
| Azure | Defender for Cloud → Event Grid |

Short dedupe windows (300s) — you want to be told about every distinct
change, not just the first one of a category.

## Infrastructure spikes — `infrastructure_spike`

Fires on CPU / memory / disk / network usage thresholds.

| Cloud | Source |
| ----- | ------ |
| GCP   | Cloud Monitoring alert on `compute.googleapis.com/instance/cpu/utilization` → Pub/Sub |
| AWS   | CloudWatch alarm on EC2/ASG / RDS / EKS metrics → SNS |
| Azure | Azure Monitor metric alert |

## Compound scenarios

You can run multiple features in the same deployment, or split them into
separate functions/lambdas for cleaner permissions and blast radius.

| Pattern | Deployment |
| ------- | ---------- |
| FinOps dashboard — budgets only | one function, one topic, `budget_alerts` on |
| FinOps + spike detection | one function, one topic, `budget_alerts` + `cost_spike` on |
| SRE dashboard — SLO + infra | one function, one topic, `service_slo` + `infrastructure_spike` on |
| Security-only | separate function, separate topic, only `security_audit` on |
