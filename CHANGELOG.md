# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No unreleased changes yet._

---

## [0.3.1] — 2026-04-25

Adds an upstream runtime manifest so the library can advertise its own
version-compatibility and deprecation status in a way operators can act
on without redeploying.

### Added

- **Runtime manifest** (`src/cloud_alert_hub/manifest.py`) — on each alert,
  the policy engine consults a small JSON descriptor at
  `https://api.github.com/repos/Tarunrj99/cloud-alert-hub/contents/.manifest.json?ref=main`
  (cached for `app.manifest.refresh_interval_seconds`, default 5 min).
  The descriptor exposes:
  - `service_status` — `active` / `paused` / `deprecated`
  - `min_supported_version` — anything older is treated as unsupported
  - `deprecated_versions` — exact versions known to have issues
  - `deployment_overrides` — per-`deployment_id` status overrides
- New `app.deployment_id` config field (and `DEPLOYMENT_ID` env var) for
  log correlation and per-deployment manifest overrides.
- `app.manifest.{enabled,url,refresh_interval_seconds,timeout_seconds,
  tolerate_network_errors,tolerate_missing_manifest}` knobs (and the
  `CLOUD_ALERT_HUB_MANIFEST_*` env-var equivalents).
- 15 new tests covering active/paused/deprecated status, version
  enforcement, deployment overrides, 404/403/410 handling, transient
  network errors with cache fallback, TTL behaviour, and the GitHub
  Contents API base64 envelope.

### Notes

- The manifest is **opt-out**: forks or air-gapped deployments can set
  `app.manifest.enabled: false` (or `CLOUD_ALERT_HUB_MANIFEST_ENABLED=false`)
  to skip the check entirely.
- Default behaviour fails-closed on 404/403/410 (so an unsupported install
  stops delivering) and tolerates transient network errors (so a brief
  upstream outage doesn't break customer alerts).
- Backward compatible: existing v0.2.x configs keep working — the manifest
  check is additive.

---

## [0.2.1] — 2026-04-25

Polish release — adds budget-specific detail fields that auditors ask about
(period, currency, remaining/overage) and makes the environment visible in
Slack notification previews.

### Added

- **Environment in the Slack header** — titles now render as
  `[HIGH · nonprod] Budget name — 120% reached` so the environment is
  visible in Slack desktop/mobile notification previews, not just after
  clicking into the message. Togglable via
  `notifications.slack.display.show_environment_in_header` (default `true`).
- **Dedicated Budget details section** for `kind=budget` alerts — renders
  a five-field grid with the budget's display name, total amount (with
  currency + amount-type label), billing period, amount spent so far, and
  either remaining or over-budget amount. Togglable via
  `notifications.slack.display.show_budget_details` (default `true`).
- **Human-readable period + amount-type labels** in the GCP adapter —
  `costIntervalStart` becomes `period_label` (`"April 2026"` for calendar
  months, `"from 2026-04-15"` for mid-month starts); `budgetAmountType`
  becomes `budget_amount_type_label` (`"Specified amount"` /
  `"Last period's amount"`). Currency code is also stored as a label so
  renderers don't have to hunt.
- **Over-budget warning styling** — when spend exceeds the budget the
  details section switches from "Remaining" to "Over budget: ⚠ $X".
- 8 new tests (47 total passing, ruff clean): env-in-header on/off, budget
  details render/hide, remaining vs overage, non-budget kinds suppressing
  the section, mid-month period labels, and amount-type label mapping.

### Notes

- Fully backward compatible with `v0.2.0` configs. Existing deployments
  will see the new sections appear automatically after bumping the pin.

---

## [0.2.0] — 2026-04-25

First production-hardening release after initial GCP nonprod deployment.

### Added

- **Native GCP Billing Budget parsing** — the `gcp_pubsub` adapter now
  auto-detects raw Cloud Billing budget notifications (`budgetDisplayName`,
  `alertThresholdExceeded`, `costAmount`, `budgetAmount`) and canonicalises
  them with real title, summary, currency-formatted metrics, threshold
  labels, and a link to the Cloud Billing console. Previously these arrived
  as a generic "GCP Alert" — they now render with full context.
- **Native GCP Cloud Monitoring incident parsing** — payloads with an
  `incident` dict (policy_name / condition_name / state / url) are now
  recognised as `kind=service` alerts with the incident URL surfaced as a
  link.
- **Richer Slack Block Kit layout** — header + severity banner + summary +
  unicode spend progress bar (budget alerts) + structured fields grid +
  metrics list + labels + links + audit footer (`event_id` / timestamp /
  route).
- **Per-section display toggles** under `notifications.slack.display.*` —
  operators can hide any of: header, summary, progress bar, fields,
  metrics, labels, links, footer, and individual fields (cloud, environment,
  project, service, owner, account, event_id, occurred_at, route). Also
  supports `label_allow_list` / `label_deny_list` / `metric_allow_list` and
  a configurable `progress_bar_width`.
- **`docs/SAMPLE_OUTPUT.md`** — ASCII previews + full Block Kit JSON for
  every severity level; explanation of the message anatomy and display
  toggles.
- **Smoke-test recipes in `docs/DEBUG_RUNBOOK.md`** — copy-paste scripts
  that publish one event per severity, a monitoring incident, an AWS SNS
  case, and a local dev-server case.
- **`examples/payloads/gcp-billing-budget-native.json`** — fixture for the
  real native budget payload shape, separate from the existing canonical
  fixture.
- **End-to-end walkthrough in `examples/gcp-cloud-function/README.md`** —
  prerequisites, Pub/Sub + API setup, pinned `requirements.txt`, deploy,
  smoke test, log tail, rollback.
- **13 new tests** — renderer toggles (hide-by-config, account redaction,
  label allow/deny), severity banner for non-budget kinds, progress bar
  cap-at-100, non-budget alerts skipping the progress section, the three
  GCP Pub/Sub input shapes (native budget, monitoring incident, canonical),
  severity mapping from threshold fractions, and currency formatting.

### Changed

- **`alert.route_key` is now populated** on every `CanonicalAlert` before
  render so the Slack footer reliably shows the chosen route.
- **Default `slack.display.show_account` is `false`** — the billing account
  ID is considered sensitive and hidden by default; flip to `true` if your
  audit requires it.
- **`config.example.yaml` recipients** are now generic
  (`finops-lead@example.com`, `sre-oncall@example.com`, etc.) with an
  annotated `display:` block.

### Removed / sanitised

- Genericised `examples/payloads/*.json` — no real company or project names.
- Genericised `config.example.yaml` and
  `examples/gcp-cloud-function/config.yaml` — no real email addresses.
- Genericised `docs/QUICKSTART.md` — generic example emails.

### Migration

- `v0.1.0 → v0.2.0` is backward-compatible: existing configs work unchanged
  and any canonical payload still renders. To get the new budget layout,
  bump the `requirements.txt` pin to `@v0.2.0` and redeploy.

---

## [0.1.0] — 2026-04-25

Initial public release.

### Added

- **Core library `cloud_alert_hub`** — installable from GitHub via
  `pip install git+https://github.com/<you>/cloud-alert-hub.git@v0.1.0`.
- **Three-layer config model** — bundled defaults ← user `config.yaml` ←
  environment variables. See
  [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
- **Feature-toggle system** with four built-in features, each a single file
  under `src/cloud_alert_hub/features/`:
  - `budget_alerts` — cloud billing budgets (GCP, AWS, Azure).
  - `service_slo` — uptime / SLO burn-rate style alerts.
  - `security_audit` — SCC, GuardDuty, Security Hub findings.
  - `infrastructure_spike` — CPU / memory / network spikes.
- **Cloud adapters** for GCP Pub/Sub (1st + 2nd gen envelopes), AWS SNS
  (Lambda + HTTP), Azure Event Grid, and a canonical `generic` source.
- **Public API** — `run(...)`, `handle_gcp_pubsub(...)`,
  `handle_aws_sns(...)`, `handle_azure_eventgrid(...)`, `load_config(...)`.
- **Notifiers** — Slack (Block Kit) and email (stdout / SMTP-pluggable).
- **Delivery** — configurable retries with exponential backoff and a
  JSON-Lines dead-letter sink for unrecoverable failures.
- **Deduplication** — in-memory or file-backed state backend keyed per
  feature.
- **Debug tooling** — `app.debug_mode` returns a `debug.trace` block on
  every response; `app.dry_run` skips actual delivery while still
  rendering; local FastAPI dev server under `examples/local-dev/` with
  `/debug/config` and `/debug/metrics`.
- **Example deployments** — ready-to-copy starters for
  GCP Cloud Function (2nd gen), AWS Lambda (SNS trigger), and a local dev
  server.
- **Documentation** — architecture, config reference, feature catalog,
  cloud-specific deployment runbooks, debug runbook, scenario catalog,
  contributing guide, security policy, and this changelog.
- **Tests & tooling** — 18 pytest tests, ruff linting, a `Makefile` with
  `venv / install / test / lint / run-server / clean` targets.

### Notes

- License: MIT.
- Supported Python: 3.10, 3.11, 3.12.
- Status: beta — API surface is considered stable but may evolve before
  1.0. Breaking changes will be called out under `## [Unreleased]`.

[Unreleased]: https://github.com/Tarunrj99/cloud-alert-hub/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.3.1
[0.2.1]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.2.1
[0.2.0]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.2.0
[0.1.0]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.1.0
