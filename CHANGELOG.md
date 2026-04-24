# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No unreleased changes yet._

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

[Unreleased]: https://github.com/Tarunrj99/cloud-alert-hub/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Tarunrj99/cloud-alert-hub/releases/tag/v0.1.0
