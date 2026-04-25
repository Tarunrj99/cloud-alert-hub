# Detection recipes

This page lists end-to-end recipes for producing canonical alerts that
`cloud-alert-hub` can claim. Recipes A–E cover the **`cost_spike`**
feature; Recipes F–G cover **`infrastructure_spike`** and
**`security_audit`** via Cloud Monitoring policies.

Each recipe uses **only built-in cloud features** — no new managed
service, no extra licensing.

The library doesn't run the detectors itself; it just renders and
deduplicates the alerts. You pick the detector that fits your cloud and
your appetite for setup. Most users start with **Recipe A** (zero
infrastructure) and graduate to **Recipe B** or **C** once they have a
stronger cost signal.

| Recipe | Cloud | Feature              | What it catches                | Infra you must add               |
|--------|-------|----------------------|--------------------------------|----------------------------------|
| A      | GCP   | `cost_spike`         | API request-rate spikes        | one Cloud Monitoring policy      |
| B      | GCP   | `cost_spike`         | True $-per-service spikes      | BigQuery billing export + SQL    |
| C      | AWS   | `cost_spike`         | Cost anomalies (any service)   | one Cost Anomaly Detection rule  |
| D      | Azure | `cost_spike`         | Cost anomalies                 | one Cost Management alert        |
| E      | any   | `cost_spike`         | Custom — your own detector     | a few dozen lines of Python      |
| F      | GCP   | `infrastructure_spike` | CPU / mem / network / log volume   | one Cloud Monitoring policy   |
| G      | GCP   | `security_audit`     | IAM / config / audit-log changes | one log-match Monitoring policy |

> Why this matters: a runaway-API event (rogue API key, leaked credential,
> mis-configured cron) would be caught by Recipe A within minutes — well
> before a monthly budget says "300 % reached". Recipe A doesn't require
> BigQuery, doesn't cost anything, and re-uses the Pub/Sub topic you've
> already wired up.

---

## When does a `cost_spike` alert fire? (and why you won't be spammed)

Two things govern timing:

1. **The detector** — how often the upstream system *evaluates* the
   condition. This is **outside** the library. You pick the detector to
   match your tolerance:

   | Recipe | Detector cadence (typical) | First-alert latency |
   |--------|----------------------------|--------------------:|
   | A — Cloud Monitoring policy        | every 1–5 min                 | ~5–15 min after the spike starts |
   | B — BigQuery scheduled query       | once / day at the cron time   | ~24 h (next BQ run)              |
   | C — AWS Cost Anomaly Detection     | once / day (AWS-managed)      | ~24 h (AWS detection cycle)      |
   | D — Azure Cost Management alert    | once / day (Azure-managed)    | ~24 h                            |
   | E — Custom detector                | whatever you schedule         | whatever you schedule            |

2. **The library's deduper** — how many Slack alerts you get *out*. The
   library keeps state in a cloud-native object store (GCS / S3 / Azure
   Blob) and applies the rule:

   > **At most one Slack alert per `(cloud, project, service, spike_period)`
   > inside `dedupe_window_seconds`.**

   With the default `dedupe_window_seconds: 86400` (one day) and the
   per-day `spike_period` label produced by Recipes A–E, that means:

   - **Recipe A** can re-fire every 5 minutes while the spike persists; you
     still get **exactly one Slack alert per service per day**.
   - When the spike re-appears the *next* day, you get **a fresh alert**
     (the `spike_period` changed, so the dedupe key changes).
   - When **another service** spikes the same day, you get **a separate
     alert** (the `service` changed, so the dedupe key changes).

This is the same pattern that protects budget alerts: the upstream system
can scream as loudly as it wants, the library guarantees Slack doesn't.

> Want hourly granularity instead of daily? Set
> `labels.spike_period` to the hour bucket (`2026-04-25T08`) at the
> publisher and shorten `dedupe_window_seconds` to `3600`. You then get
> at most one alert per service per hour.

---

## Recipe A is service-agnostic by design

Recipe A's Cloud Monitoring policy uses
`groupByFields: ["resource.label.service"]`. That tells Cloud Monitoring
to evaluate the threshold **separately for every service** that publishes
the metric — Vertex AI, Generative Language API, Cloud Run, Compute,
BigQuery, Cloud SQL, anything. There is no allow-list of services hard-
coded anywhere; whichever service spikes triggers the policy and is
named in the resulting incident's `resource.label.service`.

The library then forwards that name through to:

- the `service` field on the canonical alert
- the dedupe key (`cloud:project:service:spike_period`)
- the Slack header (`Cost spike — <service>`)

If you want to *exempt* a routinely-bursty service (e.g. `pubsub.googleapis.com`),
add it to `features.cost_spike.service_denylist` — denylisted services
are still recorded but routed at `severity=info` so they never wake you.

---

## Recipe A — GCP, no extra infrastructure

**Idea.** Cloud Monitoring already tracks per-service API request counts
in the metric `serviceruntime.googleapis.com/api/request_count`. We
attach a Pub/Sub notification channel and a *moving-average* alert
condition that fires when any service's request rate jumps more than 5×
its 7-day average.

When the policy fires, Pub/Sub delivers a Monitoring incident envelope to
the same Cloud Function that already handles your budget alerts. We tell
the library to treat this incident as a `cost_spike` (instead of the
default `service` kind) by setting **a single label on the notification
channel**: `kind=cost_spike`.

### 1. Make sure the spike feature is on

`config.yaml` of the existing Cloud Function (no redeploy needed beyond
this commit):

```yaml
features:
  cost_spike:
    enabled: true
    severity_thresholds_percent:
      medium: 100
      high: 300
      critical: 1000
    dedupe_window_seconds: 86400      # one alert per (service × day)
    route: finops
```

### 2. Reuse the existing Pub/Sub channel

Each Cloud Monitoring **notification channel** can carry a static label
map. Add `kind=cost_spike` to the existing finops channel, or create a
sibling channel that points to the same Pub/Sub topic — both work:

```bash
PROJECT_ID=my-nonprod-project
TOPIC=projects/$PROJECT_ID/topics/budget-alerts        # whatever you use
CHANNEL=projects/$PROJECT_ID/notificationChannels/...  # existing pub-sub channel

gcloud alpha monitoring channels update "$CHANNEL" \
  --update-user-labels=kind=cost_spike,environment=nonprod
```

The library transparently merges these channel labels into the Pub/Sub
**message attributes**, which the GCP adapter already inspects — that's
what triggers the cost-spike code path in
`adapters/gcp_pubsub.py::_from_cost_spike_incident`.

### 3. Create the alert policy

```bash
gcloud alpha monitoring policies create \
  --notification-channels="$CHANNEL" \
  --display-name="Per-service request-rate spike (5× of 7d avg)" \
  --policy-from-file=- <<'YAML'
displayName: Per-service request-rate spike
combiner: OR
conditions:
  - displayName: "request_count surged 5× over baseline"
    conditionThreshold:
      filter: |
        metric.type="serviceruntime.googleapis.com/api/request_count"
        resource.type="consumed_api"
      aggregations:
        - alignmentPeriod: 3600s         # 1h buckets
          perSeriesAligner: ALIGN_RATE
          crossSeriesReducer: REDUCE_SUM
          groupByFields:
            - "resource.label.service"   # ⬅ groups per-service
      comparison: COMPARISON_GT
      thresholdValue: 0                  # set via baselineConfig below
      duration: 0s
      trigger:
        count: 1
      forecastOptions: {}
combinerSettings: {}
YAML
```

Tip: use a Monitoring **forecasting** condition or the
`metric.value/baseline` ratio for true "5× of baseline". The exact
condition syntax is verbose — see the worked example in
`examples/gcp-cloud-function/scripts/spike-policy.yaml.example` for a
ready-to-apply policy file.

### 4. What you get in Slack

The alert lands in the same channel as your budget alerts:

```text
[CRITICAL · nonprod] Cost spike — Generative Language API
:rotating_light: CRITICAL  :chart_with_upwards_trend: cost_spike  :earth_asia: nonprod

Cost / usage spike detected for `Generative Language API` (state=open).

──────────────────────────────────────────
Service:                   Generative Language API
Window:                    2026-04-21
Baseline:                  9,300
Current:                   749,000
Delta:                     +7,954% :fire:

Cloud: gcp     Project: my-nonprod-project   Type: cost_spike
:link: <https://console.cloud.google.com/monitoring/alerting/incidents/x|Monitoring incident>
event_id …  •  :clock3: 2026-04-21 06:14 UTC  •  :compass: route finops
```

Note: the values shown are **request counts**, not dollars — Cloud
Monitoring sees usage, not money. That's intentional: by the time you
have dollar deltas, the spike has already happened. Recipe B converts
this to dollars if you want it.

---

## Recipe B — GCP, BigQuery billing export (true $/day per service)

When you want **dollar deltas** instead of usage deltas, push the Cloud
Billing export to BigQuery (free apart from BQ storage / query) and run a
small scheduled query that publishes anomalies to Pub/Sub.

### 1. Enable the export (one-time)

Console → Billing → **Billing export** → Standard export → pick the
target BQ dataset. Wait one full day for the first row to land in
`<dataset>.gcp_billing_export_v1_<billing_account_id>`.

### 2. Schedule the spike query

```sql
-- Save as a BigQuery scheduled query, run every 06:00 UTC.
WITH daily AS (
  SELECT
    project.id          AS project_id,
    service.description AS service,
    DATE(usage_start_time, "UTC") AS day,
    SUM(cost)           AS cost
  FROM `my-billing.project.gcp_billing_export_v1_…`
  WHERE _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  GROUP BY 1, 2, 3
),
baseline AS (
  SELECT
    project_id,
    service,
    AVG(cost) AS prev_avg
  FROM daily
  WHERE day BETWEEN DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 8 DAY)
                AND DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 1 DAY)
  GROUP BY 1, 2
),
today AS (
  SELECT * FROM daily WHERE day = DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 1 DAY)
)
SELECT
  t.project_id,
  t.service,
  t.day                                              AS spike_period,
  ROUND(b.prev_avg, 2)                               AS previous_amount,
  ROUND(t.cost, 2)                                   AS current_amount,
  ROUND(SAFE_DIVIDE(t.cost - b.prev_avg, b.prev_avg) * 100.0, 1) AS delta_percent
FROM today t
JOIN baseline b USING (project_id, service)
WHERE b.prev_avg > 1                  -- ignore noise
  AND t.cost / b.prev_avg >= 2        -- only 100%+ jumps
```

### 3. Publish results to Pub/Sub

Wrap the query in a tiny Cloud Function (or Cloud Run job) that
publishes one Pub/Sub message **per row** to your existing alerting
topic, with attributes:

```python
attrs = {
    "kind": "cost_spike",
    "service": row["service"],
    "spike_period": str(row["spike_period"]),
    "environment": "nonprod",
}
data = json.dumps({
    "title": f"Cost spike — {row['service']}",
    "summary": (
        f"{row['service']} jumped from ${row['previous_amount']:.2f} "
        f"to ${row['current_amount']:.2f} on {row['spike_period']} "
        f"(+{row['delta_percent']:.0f}%)."
    ),
    "metrics": {
        "previous_amount": float(row["previous_amount"]),
        "current_amount":  float(row["current_amount"]),
        "delta_percent":   float(row["delta_percent"]),
    },
}).encode()
publisher.publish(topic_path, data=data, **attrs)
```

This becomes a `kind=cost_spike` alert with **dollar amounts** in the
Slack message. The dedupe key `gcp:project:service:spike_period` keeps
re-runs idempotent.

---

## Recipe C — AWS, Cost Anomaly Detection → SNS

AWS already detects cost anomalies natively. Pipe them into your alerting
Lambda:

1. **Cost Explorer → Cost Anomaly Detection** → create a *monitor*
   (Service / Linked account scope) and a *subscription* with the
   threshold of your choice. Pick **"SNS topic"** as the destination.
2. Subscribe your existing `cloud-alert-hub` Lambda to that SNS topic.
   Tag the subscription with **a single message attribute**:
   `kind=cost_spike`.
3. The library's AWS adapter (`adapters/aws_sns.py`) reads the message
   attribute and emits a canonical `cost_spike` alert. The
   `metrics.previous_amount` / `current_amount` / `delta_percent` fields
   are pulled from the AWS payload (`maxImpact`, `expectedSpend`, …).

No new dashboards, no new pipelines. AWS does the detection; the library
does the rendering and deduplication.

---

## Recipe D — Azure, Cost Management alert → Action Group

1. **Cost Management** → **Cost alerts** → **Anomaly alert** for the
   subscription / resource group. Pick *"% above forecast"* as the
   trigger.
2. Wire it to an **Action Group** with a **Webhook** that points to your
   `cloud-alert-hub` Function App. Add custom property `kind=cost_spike`
   in the webhook configuration.
3. The Azure adapter (`adapters/azure_eventgrid.py`) recognises the
   `kind` property and emits a canonical `cost_spike` alert.

---

## Recipe E — Bring-your-own detector

When none of the above fit (multi-cloud, on-prem, FinOps platform), POST
JSON to the function's `/ingest/generic` endpoint:

```bash
curl -X POST "$FUNCTION_URL/ingest/generic" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $INGEST_SHARED_TOKEN" \
  -d '{
        "kind":     "cost_spike",
        "cloud":    "gcp",
        "project":  "my-nonprod-project",
        "service":  "Vertex AI",
        "summary":  "Vertex AI spend jumped from $48/day avg to $5,021 today.",
        "labels":   { "spike_period": "2026-04-21" },
        "metrics":  {
          "previous_amount":  48.13,
          "current_amount":  5021.44,
          "delta_percent":  10333.0
        }
      }'
```

The generic adapter accepts any `kind` and the cost-spike feature claims
it. This is the same shape the BigQuery scheduled-query path produces —
keep it consistent across recipes so Slack output stays uniform.

---

## Tuning notes

* **Window choice.** The dedupe key uses `labels.spike_period`. Pick a
  bucket size that matches your detector cadence — daily for Recipe B,
  hourly for Recipe A, the AWS-provided window for Recipe C.
* **Allow / deny lists.** Carve out routinely-bursty services using
  `service_allowlist` / `service_denylist`. Listed-out services are
  routed at `severity=info` rather than dropped, so you still see them
  in audit logs.
* **Severity tuning.** A 100 % jump for a service that normally costs $1
  isn't the same as a 100 % jump for one that normally costs $1 000.
  Combine the spike feature with a **floor**: only POST to the function
  when `current_amount` exceeds a small absolute threshold (e.g. $5).
* **Stacking with budgets.** Cost-spike alerts and budget alerts work
  together: spikes catch the *event* in real time, budgets catch the
  *cumulative damage*. Keep both on.

---

## Recipe F — GCP infrastructure spike via Cloud Monitoring

**Idea.** Cloud Monitoring already tracks per-resource counters — GKE
node count, network egress, container log bytes, log ingestion volume,
Compute instance count, CPU / memory utilisation. Wire any of these
policies to the same Pub/Sub topic the function already subscribes to,
tag the alerting policy with `kind=infrastructure`, and the
`infrastructure_spike` feature claims the incident automatically.

The library doesn't add a new detector; it just renders and dedupes
incidents that Cloud Monitoring already produces.

### 1. Enable the feature

```yaml
features:
  infrastructure_spike:
    enabled: true
    dedupe_window_seconds: 600   # one alert per (metric × threshold) per 10 min
    route: sre                   # or finops, or whatever route you've defined
```

### 2. Tag any existing infrastructure policy with `kind=infrastructure`

```bash
PROJECT_ID=my-nonprod-project
POLICY="projects/$PROJECT_ID/alertPolicies/0000000000000000000"   # any policy
CHANNEL="projects/$PROJECT_ID/notificationChannels/.........."   # the cloud-alert-hub Pub/Sub channel

gcloud alpha monitoring policies update "$POLICY" \
  --update-user-labels=kind=infrastructure,environment=nonprod,managed_by=cloud-alert-hub \
  --notification-channels="$CHANNEL"
```

A single command. The policy keeps firing on the same condition as before;
the only thing that changes is *where* the incident lands and which
feature claims it.

### 3. What the adapter does with it

The GCP adapter reads `incident.policy_user_labels.kind` and:

- promotes `kind` from the default `"service"` to `"infrastructure"`;
- copies `incident.metric.type` into `labels.metric` (or falls back to
  the condition / policy name);
- copies `incident.threshold_value` into `labels.threshold`;
- passes through `observed_value` and `threshold_value` as metrics so the
  Slack message can render the actual numbers;
- forwards any other operator-supplied user labels (e.g.
  `service=gke`, `severity_floor=high`) onto the canonical alert.

The dedupe key is then `cloud:project:metric:threshold` — a CPU policy
firing every five minutes for the same node pool collapses into one
Slack alert; a *different* metric (network egress, log bytes) gets its
own alert.

### 4. Reproduce locally

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source gcp \
    examples/payloads/gcp-infrastructure-spike-monitoring-incident.json | jq -r '.text'
# → :rotating_light: [CRITICAL] GKE - Node Count Exceeds 20 — GKE node count > 20 over 5 min
```

The fixture is a faithful Cloud Monitoring envelope; the `data` field is
base64-encoded JSON. Open it in any JSON viewer to inspect the shape.

---

## Recipe G — GCP security audit via Cloud Monitoring log-match policy

**Idea.** Cloud Logging exposes audit-log entries (`SetIamPolicy`,
`CreateServiceAccount`, `iam.role.update`, …) as a metric source for
Cloud Monitoring **log-match** policies. Wire one to the same Pub/Sub
topic, tag it with `kind=security`, and the `security_audit` feature
claims the incident.

This is the cheapest way to get IAM-change alerts into Slack: no
SCC subscription, no Cloud Function of your own, no BigQuery query.

### 1. Enable the feature

```yaml
features:
  security_audit:
    enabled: true
    dedupe_window_seconds: 60   # IAM changes should not be deduped aggressively
    route: security             # or whatever route you've defined
```

### 2. Wire the log-match policy

```bash
PROJECT_ID=my-nonprod-project
CHANNEL="projects/$PROJECT_ID/notificationChannels/.........."

gcloud alpha monitoring policies create \
  --notification-channels="$CHANNEL" \
  --display-name="Audit — SetIamPolicy" \
  --user-labels=kind=security,environment=nonprod,managed_by=cloud-alert-hub,resource=iam-role/admin,action=SetIamPolicy \
  --policy-from-file=- <<'YAML'
displayName: Audit — SetIamPolicy
combiner: OR
conditions:
  - displayName: "SetIamPolicy executed"
    conditionMatchedLog:
      filter: |
        protoPayload.methodName="SetIamPolicy"
        protoPayload.serviceName=("cloudresourcemanager.googleapis.com" OR "iam.googleapis.com")
YAML
```

The four operator-supplied user labels — `resource`, `action`,
`principal`, plus `kind` — give the adapter everything it needs to
populate the dedupe key (`cloud:project:resource:action:principal`)
without having to parse the audit-log payload.

If you don't pin `resource` / `action` / `principal` on the policy,
the adapter still works: it falls back to the policy name as
`resource`, the condition name as `action`, and `"unknown"` as
`principal`. You will get coarser dedupe in that case (every
audit-log incident from the same policy collapses).

### 3. Reproduce locally

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source gcp \
    examples/payloads/gcp-security-audit-monitoring-incident.json | jq -r '.text'
# → :rotating_light: [CRITICAL] Audit Config Change Detected - SetIamPolicy — Log match condition
```

### 4. Expected dedupe behaviour

| User labels on the policy                       | Dedupe key inputs                            | Effect                                   |
|-------------------------------------------------|----------------------------------------------|------------------------------------------|
| `kind=security` only                            | `policy_name`, `condition_name`, `unknown`    | One alert per policy per dedupe window   |
| `kind=security, resource=iam-role/admin`        | overrides `resource`                         | One alert per (resource × action)        |
| `kind=security, resource=…, action=…, principal=…` | all three pinned                          | Per-actor dedupe (recommended)           |

Pin the three label keys on the policy whenever you can, so each
distinct (who, did-what, on-what) gets its own Slack alert.
