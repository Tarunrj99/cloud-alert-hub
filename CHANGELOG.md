# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No unreleased changes yet._

---

## [0.4.1] — 2026-04-25

Makes **Recipe A wirable from a single `gcloud` command** and ships a
real **`preview_slack` CLI** so users can see Slack output for any
feature, locally, before deploying.

The adapter change is the headline: Cloud Monitoring's Pub/Sub
notification channel does **not** propagate channel ``user_labels`` onto
Pub/Sub message attributes — the only place an operator can tag an
alerting policy as a cost-spike source is the policy's ``userLabels``,
which Cloud Monitoring writes into the incident body under
``incident.policy_user_labels``. The adapter now reads from that
location, so a single
``gcloud alpha monitoring policies create … --user-labels=kind=cost_spike,environment=nonprod``
is enough to route every incident from that policy through the
``cost_spike`` feature with the right environment, project, service,
and spike-period labels.

### Added

- **`cloud_alert_hub.tools.preview_slack`** — first-class CLI (the
  module reference in docs is no longer a placeholder). Runs the full
  production pipeline (adapter → enrichment → feature match →
  renderer) on any payload and prints the exact Block Kit JSON the
  library would post. Works with every adapter and every feature.

  ```bash
  python -m cloud_alert_hub.tools.preview_slack \
      --source generic examples/payloads/generic-cost-spike.json
  ```

- **Per-feature payload fixtures** in `examples/payloads/` (one fixture
  per (cloud × feature)):
  - `gcp-cost-spike-monitoring-incident.json` — Recipe A.
  - `aws-cost-anomaly-sns.json` — Recipe C.
  - `generic-cost-spike.json` — Recipes B / E (dollar deltas).
  - `generic-service-slo.json`, `generic-security-audit.json`,
    `generic-infrastructure-spike.json` — one fixture per remaining
    feature.
  - All values are placeholders — no real account / project / billing
    IDs ever land in the public repo.

- **Adapter helper `_incident_user_labels()`** — merges
  ``incident.policy_user_labels`` and ``incident.user_labels`` into a
  single dict so callers can ``.get(...)`` safely.

- **`tests/test_gcp_adapter.py::test_monitoring_incident_kind_via_policy_user_labels`**
  — asserts a Cloud Monitoring incident with **no Pub/Sub attributes
  at all** is still recognised as a `cost_spike` when the alerting
  policy carries ``policy_user_labels.kind = "cost_spike"``, and that
  ``environment`` / ``project`` / ``service`` / ``spike_period`` are
  all backfilled correctly.

- **`tests/test_preview_slack.py`** — parametrised smoke test that
  renders every fixture and asserts well-formed Block Kit output, so
  the docs cannot drift from reality.

### Changed

- **`_explicit_kind()`** precedence: (1) Pub/Sub message attributes,
  (2) decoded body's top-level ``kind``, (3)
  ``incident.policy_user_labels.kind``. Existing producers (BigQuery
  scheduled query, AWS SNS, custom Recipe E POSTs) keep their old
  precedence unchanged.
- **`_from_cost_spike_incident()`** now reads ``environment``,
  ``project_id``, ``service``, and ``spike_period`` from
  ``policy_user_labels`` as a backfill source, and falls back to the
  incident's ``started_at`` UTC date when no spike-period label is set
  — so the dedupe key stays period-aware even when the operator
  doesn't bother adding one.
- Replaced deprecated `datetime.utcfromtimestamp()` with the
  timezone-aware `datetime.fromtimestamp(..., tz=timezone.utc)`.
- **`docs/RECIPES.md`** now opens with a "When does cost_spike fire?"
  section explaining the detector-cadence vs library-dedup model and
  guarantees: at most one Slack alert per (service × spike_period)
  inside `dedupe_window_seconds`, regardless of how often the upstream
  detector re-fires.
- **`docs/RECIPES.md`** gains an explicit "Recipe A is service-agnostic
  by design" section pointing at
  `groupByFields: ["resource.label.service"]`.
- **`docs/SAMPLE_OUTPUT.md`** adds real rendered output for every
  feature (`cost_spike` ×3 recipes, `service_slo`, `security_audit`,
  `infrastructure_spike`), plus a fixture table and a one-liner
  reproduce command per sample.
- **`README.md`**'s feature table now includes `cost_spike`, marks all
  five features `stable`, and points readers at the preview CLI before
  they enable anything.

### Compatibility

- Fully backward compatible. Existing canonical-payload producers and
  Pub/Sub-attribute-based producers continue to work unchanged. Only
  the zero-attribute, body-only Cloud Monitoring incident path is new.

---

## [0.4.0] — 2026-04-25

Adds the **`cost_spike`** feature — a service-agnostic, delta-triggered
alert that fires the moment a service's spend or usage jumps
significantly versus its baseline. Where `budget_alerts` tells you "you
have crossed a line you drew" (level-triggered, days late), `cost_spike`
tells you "something started behaving abnormally on day X"
(delta-triggered, minutes late).

This is the lesson from the April 2026 Gemini-key incident on the
reference deployment: the budget did fire, but only after thousands of
dollars had already been burned. A spike alert would have caught the
749 000-request day within an hour.

### Added

- **New feature `cost_spike`** (`features/cost_spike.py`)
  - Claims `alert.kind == "cost_spike"`.
  - Service-agnostic: the service comes from the payload, so a
    previously-quiet service that suddenly spikes gets caught with no
    code change. Optional `service_allowlist` / `service_denylist`
    knobs scope the feature when needed.
  - Severity ladder driven by `metrics.delta_percent` (or computed
    automatically from `previous_amount` / `current_amount`):
    `critical ≥ 1000%`, `high ≥ 300%`, `medium ≥ 100%`, else `low`.
  - Dedupe key: `cloud:project:service:spike_period`. Each
    (service × period) fires exactly once per `dedupe_window_seconds`
    (default 1 day).
- **GCP Pub/Sub adapter** now honours an explicit `kind=cost_spike`
  attribute on Cloud Monitoring incident envelopes — operators promote
  a vanilla incident into a cost-spike by adding a single label on the
  Pub/Sub notification channel. The new
  `_from_cost_spike_incident` handler pulls `current_amount` /
  `previous_amount` / `delta_percent` out of incident
  `observed_value` / `threshold_value` automatically and computes the
  delta.
- **Slack renderer** — new `cost_spike` kind emoji
  (`:chart_with_upwards_trend:`) and a dedicated *spike details* section
  showing **Service / Window / Baseline / Current / Delta** with
  ⚠️ on +300%+ and 🔥 on +1000%+ jumps. Toggle:
  `notifications.slack.display.show_spike_details`.
- **`docs/RECIPES.md`** (new) — five end-to-end detection recipes that
  use only built-in cloud features (no new managed service):
  - **Recipe A — GCP Cloud Monitoring policy** on
    `serviceruntime.googleapis.com/api/request_count` → existing
    Pub/Sub topic. Catches API-rate spikes (the Gemini-key class of
    incident) within minutes; zero new infra.
  - **Recipe B — GCP BigQuery billing export + scheduled query**
    for true $-per-service deltas.
  - **Recipe C — AWS Cost Anomaly Detection → SNS**.
  - **Recipe D — Azure Cost Management anomaly alert → Action
    Group**.
  - **Recipe E — bring-your-own detector** posting to
    `/ingest/generic`.
- `docs/SCENARIOS.md` cross-links the new feature and recipes.

### Changed

- `bundled_defaults.yaml` and `config.example.yaml` now declare a
  `cost_spike` section (`enabled: false` by default in the defaults,
  `enabled: true` in the example).
- `docs/FEATURES.md` documents the new feature alongside the existing
  five.

### Compatibility

- Backwards-compatible: existing deployments are unaffected until they
  set `features.cost_spike.enabled: true` in their own `config.yaml`.
- The Pub/Sub adapter's monitoring-incident path is unchanged unless
  the message attribute `kind=cost_spike` is present — so existing
  Cloud Monitoring policies keep landing as `kind="service"` (the old
  behaviour).

---

## [0.3.4] — 2026-04-25

Fixes a long-standing **rendering ambiguity** in budget alerts: when actual
spend has drifted past the highest configured threshold (e.g. you crossed
300% but you're already at 371%), the Slack message used to print
"Spend has reached *300%* of the budget ($37,068 of $10,000)" and a
progress bar labelled "300%". A reader could easily misread that as
"current spend equals 300%". Now the alert shows the true spend ratio
*and* names the threshold that was crossed.

### Changed

- **GCP Pub/Sub adapter** (`adapters/gcp_pubsub.py::_from_native_budget`)
  - Title changed from `"X% reached"` to `"X% threshold reached"`.
  - Summary uses the simple form (`"Spend has reached X% of the budget …"`)
    only when actual spend ratio is within 5pp of the threshold. Otherwise
    it switches to: `"Crossed the *X%* budget threshold — current spend is
    $Y of $Z (*A%* of budget)."`
  - New canonical fields: `metrics["actual_percent"]` (float) and
    `labels["actual_percent"]` (str), both computed from
    `cost_amount / budget_amount`.
- **Slack renderer** (`renderer.py::_progress_block`)
  - Progress bar percentage now reflects the *actual* `cost / budget` ratio
    instead of `alertThresholdExceeded`. The bar still caps visually at the
    configured width but the numeric label tells the truth.
  - When actual ratio differs from the crossed threshold by ≥5pp, the
    heading appends `(crossed *X%* threshold)` so both numbers are visible.
- Existing renderer + adapter tests updated; two new regression tests
  cover the over-budget case end-to-end.

### Fixed

- Removes the misleading "300%" label on alerts where actual spend is
  significantly past the highest configured threshold step.

---

## [0.3.3] — 2026-04-25

Adds **persistent, multi-cloud dedup state** so serverless deployments
fire each budget threshold exactly once per billing period — even across
function cold starts. Previously, in-memory dedup state was wiped every
~10–30 minutes when the platform recycled the function instance, causing
the same threshold message to re-fire every time the source (GCP Cloud
Billing, AWS Budgets, Azure Cost Management) re-emitted it (~22-minute
interval). At 300% spend that meant ~2,000 duplicate Slack alerts per
month per deployment.

### Added

- Three new state backends — all optional extras, each using its cloud's
  native object storage (no new managed service introduced):
  - `GCSState` — `pip install 'cloud-alert-hub[gcp]'`
  - `S3State` — `pip install 'cloud-alert-hub[aws]'`
  - `AzureBlobState` — `pip install 'cloud-alert-hub[azure]'`
- Shared `_ObjectStoreState` base with optimistic-concurrency retries,
  expiry GC, and a small in-memory fake for tests.
- `state.{bucket,object_path,region,account_name,container,blob_name,
  connection_string_env}` config keys + matching env-var overrides
  (`STATE_BUCKET`, `STATE_OBJECT_PATH`, …) — see
  [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
- New end-to-end Azure deploy guide
  ([`docs/DEPLOY_AZURE.md`](docs/DEPLOY_AZURE.md)) covering Storage Account
  + container + Managed-Identity RBAC for the Azure Blob backend.
- Eleven new state-backend tests covering: in-memory fake of the cloud
  base class, dedup-window semantics, concurrent-write conflict + retry,
  expiry GC, factory routing, and "missing required key" error messages.
- Two new budget-feature tests covering the period-aware dedup key.

### Changed

- **Budget feature dedup key now includes the billing period.** It went
  from `cloud:project:budget:threshold` to
  `cloud:project:budget:cost_interval_start:threshold`. This means the
  same threshold inside the same billing month dedups for the *whole
  month* (no matter how big `dedupe_window_seconds` is), but a fresh
  month re-fires from 50% as expected.
- Default `features.budget_alerts.dedupe_window_seconds` raised from
  `1800` (30 min) to `2764800` (32 days) in `bundled_defaults.yaml` and
  `config.example.yaml`. With the new period-aware key + cloud-native
  state backend, this guarantees exactly-once delivery per (threshold,
  billing-period) pair.
- `docs/DEPLOY_GCP.md` and `docs/DEPLOY_AWS.md` got new "Create the
  dedup-state bucket" sections + IAM grants + troubleshooting rows for
  the new failure modes (missing extras, missing IAM).
- `examples/gcp-cloud-function/` and `examples/aws-lambda/` configs and
  README's now wire the GCS / S3 backends by default; `requirements.txt`
  files use `cloud-alert-hub[gcp]` / `cloud-alert-hub[aws]` extras.

### Migration notes

Existing deployments keep working unmodified — `state.backend: memory`
remains the default, and the previous (period-less) dedup key is a strict
prefix of the new key, so re-deploys won't replay history. To enable the
new persistent dedup:

1. Create a small object-store bucket / container in your cloud.
2. Grant the function's runtime service account / role read+write on it.
3. Update `requirements.txt` to use the matching extra
   (`cloud-alert-hub[gcp|aws|azure]`).
4. Set `state.backend` and the corresponding bucket/container keys in
   `config.yaml`.
5. Bump `dedupe_window_seconds` to at least `2764800` (32 days) so a full
   billing period is covered.

See the per-cloud deploy docs for copy-pasteable commands.

---

## [0.3.2] — 2026-04-25

Fixes Slack/email rendering on native cloud-vendor budget payloads. Cloud
Billing (GCP) and Budgets (AWS) Pub/Sub / SNS messages don't carry an
`environment` or `project_id` attribute, so previous releases rendered
`Environment: unknown` and dropped the `Project:` field entirely. The
pipeline now backfills both from operator config.

### Added

- New `app.project` config field — names the project / account ID the
  alerts originate from. Surfaced in Slack/email as the `Project:` field.
- Automatic fallback to runtime env vars (`GOOGLE_CLOUD_PROJECT`,
  `GCP_PROJECT`, `AWS_ACCOUNT_ID`) when `app.project` is empty — Cloud
  Functions / Cloud Run / Lambda set these for free, so existing
  deployments inherit a sensible default with zero config edits.
- Four new tests: env backfill, project backfill from `app.project`,
  project backfill from `GOOGLE_CLOUD_PROJECT`, and explicit-payload-wins
  precedence.

### Fixed

- `Environment: unknown` shown for native GCP budget alerts whose Pub/Sub
  envelope had no `environment` attribute. Now resolves to the value of
  `app.environment` from the deployment config.
- Severity header banner missing the environment suffix
  (`[CRITICAL]` instead of `[CRITICAL · nonprod]`) for the same reason.
- `Project:` field hidden on native budget alerts because the adapter
  couldn't find a `project_id` attribute. Now backfilled from
  `app.project` or the cloud-runtime env var.

### Notes

- The fix is implemented once in the API layer (`api.py::_enrich_from_config`)
  so all adapters (GCP, AWS, Azure, generic) benefit.
- Explicit values from the upstream payload always win over config.
  Backfill only happens when the canonical alert has no value.

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

[Unreleased]: https://github.com/Tarunrj99/cloud-alert-hub/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.4.0
[0.3.4]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.3.4
[0.3.3]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.3.3
[0.3.2]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.3.2
[0.3.1]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.3.1
[0.2.1]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.2.1
[0.2.0]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.2.0
[0.1.0]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.1.0
