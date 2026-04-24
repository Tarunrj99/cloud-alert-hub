# Sample Output

What an alert actually looks like once it lands in Slack, for every severity
the library produces. All samples below come from the *real* renderer driven
by the real [`gcp-billing-budget-native.json`](../examples/payloads/gcp-billing-budget-native.json)
fixture at different threshold fractions (50%, 90%, 120%, 210%).

> Reproduce these any time with:
>
> ```bash
> python -m cloud_alert_hub.tools.preview_slack  # not a real CLI — see DEBUG_RUNBOOK.md
> ```
>
> …or by running the renderer directly as shown at the bottom of this page.

Contents:
- [Severity matrix](#severity-matrix)
- [50% — LOW](#50--low)
- [90% — MEDIUM](#90--medium)
- [120% — HIGH](#120--high)
- [210% — CRITICAL](#210--critical)
- [Anatomy of a message](#anatomy-of-a-message)
- [Full Block Kit JSON (120% case)](#full-block-kit-json-120-case)
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
| 6 | **Budget details**        | `show_budget_details` | **Budget alerts only** — name, amount (currency + type), billing period, spent, remaining/overage |
| 7 | Fields grid               | `show_fields` + `show_cloud` / `show_environment` / `show_project` / `show_service` / `show_kind` / `show_owner` / `show_account` | Structured key/value cells |
| 8 | Metrics list              | `show_metrics` | Numeric metrics like `cost_amount`, `error_rate_percent` |
| 9 | Labels list               | `show_labels` | Free-form label dict (opt-in — chatty) |
|10 | Links / Runbook           | `show_links` | Runbook URL + any payload-provided links |
|11 | Footer                    | `show_footer` + `show_event_id` / `show_occurred_at` / `show_route` | Audit trail info |

## Full Block Kit JSON (120% case)

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

```bash
python - <<'PY'
import base64, json
from cloud_alert_hub.adapters.gcp_pubsub import from_gcp_pubsub
from cloud_alert_hub.features.budget import BudgetAlertsFeature
from cloud_alert_hub.renderer import render_slack

inner = {
  "budgetDisplayName": "Example Nonprod Monthly Budget",
  "budgetAmount": 10000.0, "costAmount": 12000.0, "currencyCode": "USD",
  "alertThresholdExceeded": 1.2,
  "costIntervalStart": "2026-04-01T00:00:00Z",
  "budgetAmountType": "SPECIFIED_AMOUNT"
}
env = {"message": {"data": base64.b64encode(json.dumps(inner).encode()).decode(),
                   "attributes": {"project_id":"my-nonprod-project","environment":"nonprod"}}}

alert = from_gcp_pubsub(env)
match = BudgetAlertsFeature({"route":"finops"}).match(alert)
alert.severity = match.severity
alert.labels.update(match.labels)
alert.route_key = "finops"

msg = render_slack(alert, channel="#alerts-finops",
                   display={"show_account": False, "progress_bar_width": 22})
print(json.dumps({"channel": msg.channel, "text": msg.text, "blocks": msg.blocks}, indent=2))
PY
```
