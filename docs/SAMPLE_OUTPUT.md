# Sample Output

What an alert actually looks like once it lands in Slack, for every severity
the library produces. All samples below come from the *real* renderer driven
by the real [`gcp-billing-budget-native.json`](../examples/payloads/gcp-billing-budget-native.json)
fixture at different threshold fractions (50%, 90%, 120%, 210%).

> Reproduce **any** of these locally without sending anything to Slack:
>
> ```bash
> # any feature, any cloud, any payload — just point it at one of
> # examples/payloads/* and pass --source gcp|aws|azure|generic
> python -m cloud_alert_hub.tools.preview_slack \
>     --source generic examples/payloads/generic-cost-spike.json
> ```
>
> Output is the exact Block Kit JSON the library would POST to Slack —
> paste it into [Slack's Block Kit Builder](https://api.slack.com/tools/block-kit-builder)
> to see the rendered card visually.

Contents:
- [Severity matrix](#severity-matrix)
- Budget alerts
  - [50% — LOW](#50--low)
  - [90% — MEDIUM](#90--medium)
  - [120% — HIGH](#120--high)
  - [210% — CRITICAL](#210--critical)
- Cost-spike alerts
  - [Cost spike — Recipe A (Cloud Monitoring)](#cost-spike--recipe-a-cloud-monitoring)
  - [Cost spike — Recipe B/E (dollar deltas)](#cost-spike--recipe-be-dollar-deltas)
  - [Cost spike — Recipe C (AWS Cost Anomaly)](#cost-spike--recipe-c-aws-cost-anomaly)
- Other features
  - [Service SLO breach](#service-slo-breach)
  - [Security audit finding](#security-audit-finding)
  - [Infrastructure spike](#infrastructure-spike)
- [Anatomy of a message](#anatomy-of-a-message)
- [Full Block Kit JSON (120% budget case)](#full-block-kit-json-120-budget-case)
- [Hiding sections with `slack.display`](#hiding-sections-with-slackdisplay)
- [Reproducing locally](#reproducing-locally)

## Severity matrix

| Threshold crossed | Severity | Slack emoji | Colour cue |
| ----------------: | :------- | :---------- | :--------- |
| `< 50%`           | `info`      | ℹ️ `:information_source:` | blue |
| `50% – 89%`       | `low`       | 🟡 `:large_yellow_circle:` | yellow |
| `90% – 99%`       | `medium`    | 🔶 `:large_orange_diamond:` | orange |
| `100% – 199%`     | `high`      | 🔴 `:red_circle:` | red |
| `≥ 200%`          | `critical`  | 🚨 `:rotating_light:` | flashing red |

Severity is set by `BudgetAlertsFeature._severity_for_threshold` — see
[`src/cloud_alert_hub/features/budget.py`](../src/cloud_alert_hub/features/budget.py).

## 50% — LOW

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [LOW · nonprod] Example Nonprod Monthly Budget — 50% reached            │
├─────────────────────────────────────────────────────────────────────────┤
│  🟡 LOW    💰 budget    🌏 nonprod                                        │
│                                                                         │
│  Spend has reached 50% of the budget ($5,000.00 of $10,000.00).         │
│                                                                         │
│  Spend progress: ███████████░░░░░░░░░░░ 50%                              │
│  Spent $5,000.00 of $10,000.00                                           │
│  ─────────────────────────────────────────────────────────────────      │
│  Budget name:      Example Nonprod Monthly Budget                       │
│  Budget amount:    $10,000.00 (Specified amount)                        │
│  Billing period:   April 2026                                           │
│  Spent so far:     $5,000.00                                            │
│  Remaining:        $5,000.00                                            │
│  ─────────────────────────────────────────────────────────────────      │
│  Cloud           Environment         Project              Type           │
│  gcp             nonprod             my-nonprod-project   budget         │
│                                                                         │
│  Metrics                                                                 │
│  • cost_amount:   $5,000.00                                              │
│  • budget_amount: $10,000.00                                             │
│                                                                         │
│  🔗 Budget console                                                       │
│  event_id f6cd9fbf-…  •  🕒 2026-04-25 09:00 UTC  •  🧭 route finops     │
└─────────────────────────────────────────────────────────────────────────┘
```

## 90% — MEDIUM

```
[MEDIUM · nonprod] Example Nonprod Monthly Budget — 90% reached
🔶 MEDIUM    💰 budget    🌏 nonprod

Spend has reached 90% of the budget ($9,000.00 of $10,000.00).
Spend progress: ████████████████████░░ 90%
Spent $9,000.00 of $10,000.00
───────────────────────────
Budget name:      Example Nonprod Monthly Budget
Budget amount:    $10,000.00 (Specified amount)
Billing period:   April 2026
Spent so far:     $9,000.00
Remaining:        $1,000.00
…same Cloud / Environment / Project / Metrics / footer as above…
```

## 120% — HIGH

```
[HIGH · nonprod] Example Nonprod Monthly Budget — 120% reached
🔴 HIGH    💰 budget    🌏 nonprod

Spend has reached 120% of the budget ($12,000.00 of $10,000.00).
Spend progress: ██████████████████████ 120%    ← bar is capped at 100%
Spent $12,000.00 of $10,000.00
───────────────────────────
Budget name:      Example Nonprod Monthly Budget
Budget amount:    $10,000.00 (Specified amount)
Billing period:   April 2026
Spent so far:     $12,000.00
Over budget:      ⚠ $2,000.00
…
```

## 210% — CRITICAL

```
[CRITICAL · nonprod] Example Nonprod Monthly Budget — 210% reached
🚨 CRITICAL    💰 budget    🌏 nonprod

Spend has reached 210% of the budget ($21,000.00 of $10,000.00).
Spend progress: ██████████████████████ 210%    ← bar is capped at 100%
Spent $21,000.00 of $10,000.00
───────────────────────────
Budget name:      Example Nonprod Monthly Budget
Budget amount:    $10,000.00 (Specified amount)
Billing period:   April 2026
Spent so far:     $21,000.00
Over budget:      ⚠ $11,000.00
…
```

## Cost spike — Recipe A (Cloud Monitoring)

Source: a Cloud Monitoring incident routed through a Pub/Sub notification
channel labelled `kind=cost_spike`. The library converts the incident
into a `cost_spike` canonical alert and uses the
`resource.label.service` reported by Monitoring as the service name —
**any service** that hits the threshold lands here, not just LLM APIs.

```text
[HIGH · nonprod] Cost spike — generativelanguage.googleapis.com
🔴 HIGH    📈 cost_spike    🌏 nonprod

Request rate for generativelanguage.googleapis.com is 212.4/s, more than
5x the 7-day baseline (20.0/s).

──────────────────────────────────────────
Service:                 generativelanguage.googleapis.com
Window:                  2026-04-25
──────────────────────────────────────────
Cloud           Environment        Project                 Service                                Type
gcp             nonprod            my-nonprod-project      generativelanguage.googleapis.com      cost_spike

🔗 https://console.cloud.google.com/monitoring/alerting/incidents/cm-incident-0001
event_id …  •  🕒 2026-04-25 08:30 UTC  •  🧭 route finops
```

Reproduce locally:

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source gcp examples/payloads/gcp-cost-spike-monitoring-incident.json
```

## Cost spike — Recipe B/E (dollar deltas)

Source: a BigQuery scheduled query (Recipe B) or any custom detector
(Recipe E) that publishes a canonical payload with `previous_amount` and
`current_amount` in dollars. The library computes `delta_percent`, picks
severity from the configured ladder (`+100% → medium`, `+300% → high`,
`+1000% → critical`), and renders dollar amounts in the message.

```text
[CRITICAL · nonprod] Cost spike detected — generativelanguage.googleapis.com
🚨 CRITICAL    📈 cost_spike    🌏 nonprod

Daily spend on generativelanguage.googleapis.com jumped from $12.40
(7-day median) to $4,021.55 today (+32,330%).

──────────────────────────────────────────
Service:                 generativelanguage.googleapis.com
Window:                  2026-04-25
Delta:                   +32,330% 🔥
──────────────────────────────────────────
Cloud           Environment        Project                 Service                               Type
gcp             nonprod            my-nonprod-project      generativelanguage.googleapis.com     cost_spike

Metrics
• previous_amount_usd: 12.40
• current_amount_usd:  4,021.55
• delta_percent:       32,330.00

📚 Runbook   🔗 Billing console
event_id …  •  🕒 2026-04-25 10:19 UTC  •  🧭 route finops
```

Reproduce locally:

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source generic examples/payloads/generic-cost-spike.json
```

## Cost spike — Recipe C (AWS Cost Anomaly)

Source: AWS Cost Anomaly Detection → SNS topic with message attribute
`kind=cost_spike`. The AWS adapter emits a canonical `cost_spike` alert
exactly the same shape as Recipe B/E, so the renderer treats them
identically — only the cloud, service name, and `links` differ.

```text
[CRITICAL · nonprod] AWS Cost Anomaly — Bedrock
🚨 CRITICAL    📈 cost_spike    🌏 nonprod

AWS Cost Anomaly Detection flagged Amazon Bedrock spend at $1,847.20
today vs $42.10 7-day baseline (+4,287%).
…
```

Reproduce locally:

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source aws examples/payloads/aws-cost-anomaly-sns.json
```

## Service SLO breach

Source: any payload with `kind=service`. Severity is decided by the
`service_slo` feature using the metrics in the payload (defaulting to
`medium` when SLO breach percent isn't explicit).

```text
[MEDIUM · nonprod] Service SLO breach — checkout-api error rate
🔶 MEDIUM    🛠 service    🌏 nonprod

checkout-api error rate is 4.2% over the last 5 minutes (SLO: <1%).

Cloud: gcp     Environment: nonprod     Project: my-nonprod-project
Service: checkout-api     Type: service     Owner: platform

Metrics
• error_rate_percent: 4.20
• p99_latency_ms:     1,820
• request_count:      12,450

📚 Runbook   🔗 Dashboard
event_id …  •  🕒 …  •  🧭 route platform
```

Reproduce locally:

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source generic examples/payloads/generic-service-slo.json
```

## Security audit finding

Source: any payload with `kind=security`. Typically driven by Cloud
Audit Logs (`SetIamPolicy`, `SetIamPermissions`, role grants on
sensitive accounts).

```text
[MEDIUM · nonprod] IAM policy change on production-like service account
🔶 MEDIUM    🔐 security    🌏 nonprod

User user@example.com granted roles/owner on service account
svc-deploy@my-nonprod-project.iam.gserviceaccount.com.

Cloud: gcp     Environment: nonprod     Project: my-nonprod-project
Type: security     Owner: secops

🔗 Audit log
event_id …  •  🕒 …  •  🧭 route secops
```

Reproduce locally:

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source generic examples/payloads/generic-security-audit.json
```

## Infrastructure spike

Source: any payload with `kind=infrastructure`. Typical triggers: GKE
node CPU/memory saturation, persistent-disk ops/sec spikes, network
egress surges.

```text
[MEDIUM · nonprod] GKE node CPU saturation — gke-data-pool
🔶 MEDIUM    🖧 infrastructure    🌏 nonprod

Average CPU on node pool gke-data-pool is 92% over the last 10 minutes
(threshold: 85%).

Cloud: gcp     Environment: nonprod     Project: my-nonprod-project
Service: gke   Type: infrastructure     Owner: platform

Metrics
• cpu_utilization_percent:    92.00
• memory_utilization_percent: 71.40
• node_count:                 8

🔗 Cluster
event_id …  •  🕒 …  •  🧭 route platform
```

Reproduce locally:

```bash
python -m cloud_alert_hub.tools.preview_slack \
    --source generic examples/payloads/generic-infrastructure-spike.json
```

## Anatomy of a message

A rendered alert is composed of these Block Kit sections, top to bottom.
Each one can be suppressed individually via `notifications.slack.display.*`:

| # | Section | Config key | Notes |
|--:|---------|-----------|-------|
| 1 | Header                    | `show_header` + `show_environment_in_header` | Plain-text title with severity pill; environment is prefixed so it's visible in Slack notification previews |
| 2 | Severity + kind banner    | `show_header` | Emoji + severity + kind + environment |
| 3 | Summary                   | `show_summary` | 1-2 line human-readable description |
| 4 | Progress bar              | `show_progress_bar` | Budget alerts only |
| 5 | Divider                   | implicit | Only rendered when fields are shown |
| 6a | **Budget details**       | `show_budget_details` | **Budget alerts only** — name, amount (currency + type), billing period, spent, remaining/overage |
| 6b | **Spike details**        | `show_spike_details`  | **Cost-spike alerts only** — service, spike window, baseline / current amount, delta % with 🔥 emoji on +1000% |
| 7 | Fields grid               | `show_fields` + `show_cloud` / `show_environment` / `show_project` / `show_service` / `show_kind` / `show_owner` / `show_account` | Structured key/value cells |
| 8 | Metrics list              | `show_metrics` | Numeric metrics like `cost_amount`, `error_rate_percent` |
| 9 | Labels list               | `show_labels` | Free-form label dict (opt-in — chatty) |
|10 | Links / Runbook           | `show_links` | Runbook URL + any payload-provided links |
|11 | Footer                    | `show_footer` + `show_event_id` / `show_occurred_at` / `show_route` | Audit trail info |

## Full Block Kit JSON (120% budget case)

This is the *actual* payload sent to Slack's incoming webhook. Paste it into
Slack's [Block Kit Builder](https://api.slack.com/tools/block-kit-builder) to
preview visually.

```json
{
  "channel": "#alerts-finops",
  "text": ":red_circle: [HIGH] Example Nonprod Monthly Budget — 120% reached",
  "blocks": [
    { "type": "header",
      "text": { "type": "plain_text", "emoji": true,
                "text": "[HIGH · nonprod] Example Nonprod Monthly Budget — 120% reached" } },

    { "type": "section",
      "text": { "type": "mrkdwn",
                "text": ":red_circle: *HIGH*   :moneybag: `budget`   :earth_asia: `nonprod`" } },

    { "type": "section",
      "text": { "type": "mrkdwn",
                "text": "Spend has reached *120%* of the budget ($12,000.00 of $10,000.00)." } },

    { "type": "section",
      "text": { "type": "mrkdwn",
                "text": "*Spend progress:* `██████████████████████` *120%*\nSpent $12,000.00  of  $10,000.00" } },

    { "type": "divider" },

    { "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Budget name:*\n`Example Nonprod Monthly Budget`" },
        { "type": "mrkdwn", "text": "*Budget amount:*\n$10,000.00  _(Specified amount)_" },
        { "type": "mrkdwn", "text": "*Billing period:*\nApril 2026" },
        { "type": "mrkdwn", "text": "*Spent so far:*\n$12,000.00" },
        { "type": "mrkdwn", "text": "*Over budget:*\n:warning: $2,000.00" }
      ] },

    { "type": "divider" },

    { "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Cloud:*\n`gcp`" },
        { "type": "mrkdwn", "text": "*Environment:*\n`nonprod`" },
        { "type": "mrkdwn", "text": "*Project:*\n`my-nonprod-project`" },
        { "type": "mrkdwn", "text": "*Type:*\n`budget`" }
      ] },

    { "type": "section",
      "text": { "type": "mrkdwn",
                "text": "*Metrics*\n• `cost_amount`: $12,000.00\n• `budget_amount`: $10,000.00" } },

    { "type": "context",
      "elements": [
        { "type": "mrkdwn",
          "text": ":link: <https://console.cloud.google.com/billing/budgets|Budget console>" } ] },

    { "type": "context",
      "elements": [
        { "type": "mrkdwn",
          "text": "`event_id` 7e53db92-…   •   :clock3: 2026-04-25 09:00 UTC   •   :compass: route `finops`" } ] }
  ]
}
```

## Hiding sections with `slack.display`

Every visual knob is configurable. For example, if your org doesn't want the
billing account ID, project name, or labels surfaced in Slack at all:

```yaml
notifications:
  slack:
    display:
      show_account:     false
      show_project:     false        # hide project ID too
      show_labels:      false
      show_owner:       false
      label_deny_list:  ["cost_center", "internal_tag"]
      metric_allow_list: ["cost_amount", "budget_amount"]   # hide everything else
```

Minimal "audit-safe" variant:

```yaml
notifications:
  slack:
    display:
      show_header:        true
      show_summary:       true
      show_progress_bar:  true
      show_fields:        false
      show_metrics:       false
      show_labels:        false
      show_links:         false
      show_footer:        true
      show_event_id:      true
      show_occurred_at:   true
      show_route:         false
```

Flipping all eight top-level toggles off produces a message with only the
webhook's fallback text — useful in smoke tests that just want to assert
"webhook reachable".

## Reproducing locally

The same `preview_slack` CLI is the canonical entrypoint for all five
features and all four cloud sources. It runs the **identical pipeline**
the production Cloud Function / Lambda runs (adapter → enrichment →
feature match → renderer) but stops just before the notifier — nothing
leaves your machine.

```bash
# install the package in editable mode (one-time)
pip install -e '.[gcp,aws,azure]'

# preview any payload, any source
python -m cloud_alert_hub.tools.preview_slack \
    --source generic examples/payloads/generic-cost-spike.json

# render only the Block Kit blocks (paste into Slack Block Kit Builder):
python -m cloud_alert_hub.tools.preview_slack \
    --source gcp --blocks-only examples/payloads/gcp-billing-budget-native.json

# preview with your own deployment config:
python -m cloud_alert_hub.tools.preview_slack \
    --source gcp --config nonprod/config.yaml event.json
```

Available payload fixtures (all values are placeholders — real account
IDs, project IDs, and billing IDs are never committed):

| Fixture                                               | Source     | Feature           |
|-------------------------------------------------------|------------|-------------------|
| `gcp-billing-budget-native.json`                      | `gcp`      | `budget_alerts`   |
| `gcp-cost-spike-monitoring-incident.json`             | `gcp`      | `cost_spike`      |
| `aws-sns-event.json`                                  | `aws`      | `budget_alerts`   |
| `aws-cost-anomaly-sns.json`                           | `aws`      | `cost_spike`      |
| `generic-budget-alert.json`                           | `generic`  | `budget_alerts`   |
| `generic-cost-spike.json`                             | `generic`  | `cost_spike`      |
| `generic-service-slo.json`                            | `generic`  | `service_slo`     |
| `generic-security-audit.json`                         | `generic`  | `security_audit`  |
| `generic-infrastructure-spike.json`                   | `generic`  | `infrastructure_spike` |
