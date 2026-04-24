<!-- -*- markdown -*- -->

<h1 align="center">cloud-alert-hub</h1>

<p align="center">
  <b>A cloud-agnostic alerting hub.</b><br>
  Ingests billing, SLO, security, and infrastructure events from any cloud
  (GCP Pub/Sub, AWS SNS, Azure Event Grid, or any JSON source) and delivers
  them to Slack and email, driven by a single YAML config.
</p>

<p align="center">
  <i>One codebase. Any cloud. One config file per deployment.</i>
</p>

<p align="center">
  <a href="#"><img alt="python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="CHANGELOG.md"><img alt="status" src="https://img.shields.io/badge/status-beta-blue"></a>
  <a href="#deployment-recipes"><img alt="platform" src="https://img.shields.io/badge/platform-GCP%20%7C%20AWS%20%7C%20Azure-orange"></a>
  <a href="CONTRIBUTING.md"><img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen"></a>
</p>

<p align="center">
  <a href="#quick-start--5-minutes">Quick start</a> ·
  <a href="docs/QUICKSTART.md">Full tutorial</a> ·
  <a href="docs/CONFIGURATION.md">Config</a> ·
  <a href="docs/FEATURES.md">Features</a> ·
  <a href="docs/SAMPLE_OUTPUT.md">Sample output</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a> ·
  <a href="docs/DEBUG_RUNBOOK.md">Debug</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

---

## Why this project exists

Most alerting stacks end up as a tangle of per-cloud scripts: one Lambda for
AWS Budgets, one Cloud Function for GCP Monitoring, another for Azure, each
with its own Slack formatting bug and its own list of recipients to keep in
sync. This repo is the opposite:

* **One library** (`cloud_alert_hub`) contains all the policy, dedupe, routing,
  rendering, retries, dead-lettering, and Slack/email plumbing.
* **One config file** per deployment enables/disables features and overrides
  anything (channels, thresholds, routes) without touching code.
* **Any runtime** (Cloud Function, Lambda, Cloud Run, or a local FastAPI
  server) is a ~10-line wrapper that imports the library and passes the
  event through.

Adding a new alerting scenario = one Python file under
[`src/cloud_alert_hub/features/`](src/cloud_alert_hub/features/). Rolling it out to a
new environment = one `config.yaml`.

---

## Table of contents

1. [Requirements](#requirements)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [Repository layout](#repository-layout)
4. [Quick start — 5 minutes](#quick-start--5-minutes)
5. [Configuration model](#configuration-model)
6. [Feature catalog](#feature-catalog)
7. [Deployment recipes](#deployment-recipes)
8. [Running many features from one repo](#running-many-features-from-one-repo)
9. [Local development](#local-development)
10. [Debugging and audit](#debugging-and-audit)
11. [Extending](#extending)
12. [Docs index](#docs-index)
13. [Contributing](#contributing)
14. [Security](#security)
15. [License](#license)

---

## Requirements

### On your workstation

| Tool | Version | Purpose |
| ---- | ------- | ------- |
| Python | **3.10+** | Library runtime (3.10 / 3.11 / 3.12 are tested) |
| `pip` | any recent | Installs the library from GitHub |
| `git` | any recent | Cloning and publishing your fork |
| `gcloud` CLI | latest | Only if deploying on GCP |
| AWS CLI v2 | latest | Only if deploying on AWS |

### Cloud accounts & permissions

| Cloud | You need |
| ----- | -------- |
| **GCP** | A project with billing enabled, IAM roles: `roles/cloudfunctions.admin`, `roles/pubsub.admin`, `roles/iam.serviceAccountUser`. APIs: Cloud Functions, Cloud Run, Eventarc, Pub/Sub, Cloud Build. |
| **AWS** | An AWS account, IAM permissions: `lambda:*`, `iam:PassRole`, `sns:Subscribe`. A Lambda execution role (`AWSLambdaBasicExecutionRole` is enough). |
| **Azure** | Resource group with permission to create Function Apps + Event Grid subscriptions. |

### External services

* **Slack incoming webhook URL** — create one at
  [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks).
* (Optional) **SMTP / SES / SendGrid** credentials if you plan to enable
  email delivery. The library ships with a `stdout` email provider by
  default so you can test without any email setup.

### Python dependencies

Declared in [`pyproject.toml`](pyproject.toml):

* Runtime: `pydantic >= 2.9`, `pyyaml >= 6.0`, `httpx >= 0.27`.
* Local dev server (`[server]` / `[dev]` extras): `fastapi`, `uvicorn`,
  `python-dotenv`.

---

## Architecture at a glance

```
┌────────────────────┐
│  Cloud source      │  GCP Billing Budget · Cloud Monitoring ·
│  (Pub/Sub, SNS,    │  AWS Budgets · CloudWatch · SecurityHub ·
│   Event Grid, …)   │  Azure Monitor · any JSON publisher
└──────────┬─────────┘
           │ event
           ▼
┌────────────────────┐       ┌───────────────────────────────┐
│  Runtime wrapper   │──────▶│           cloud_alert_hub         │
│  (Cloud Function,  │       │  adapter → policy → render →  │
│   Lambda, server)  │       │  notifier (Slack, email, …)   │
└────────────────────┘       └───────────────┬───────────────┘
  10 lines of code                            │
                                              ▼
                                      ┌──────────────────┐
                                      │ Slack · Email    │
                                      │ Dead-letter file │
                                      └──────────────────┘
```

The wrapper is platform-specific (each cloud has its own event shape and
entrypoint signature). Everything downstream of it is cloud-agnostic.

---

## Repository layout

```
cloud-alert-hub/
├── README.md                        ← you are here
├── LICENSE                          ← MIT
├── pyproject.toml                   ← installable as `cloud-alert-hub`
├── config.example.yaml              ← the one file users copy & edit
├── Makefile                         ← common dev tasks
├── .env.example
├── .gitignore
│
├── src/cloud_alert_hub/                 ← the library
│   ├── __init__.py                  ← public API surface
│   ├── api.py                       ← run(), handle_gcp_pubsub(), …
│   ├── config.py                    ← YAML + env merge
│   ├── bundled_defaults.yaml        ← ships with the package (safe defaults)
│   ├── models.py                    ← CanonicalAlert + DeliveryTarget
│   ├── policy.py                    ← feature-driven routing & dedupe
│   ├── processor.py                 ← render · deliver · retry · dead-letter
│   ├── renderer.py                  ← Slack Block Kit + email bodies
│   ├── state.py                     ← in-memory / file-backed dedupe
│   ├── telemetry.py                 ← counters
│   ├── deadletter.py                ← .jsonl sink for unrecoverable deliveries
│   ├── security.py                  ← shared-token auth (local dev only)
│   ├── adapters/                    ← gcp_pubsub, aws_sns, azure_eventgrid, generic
│   ├── notifiers/                   ← slack, email
│   └── features/                    ← each file = one toggleable scenario
│       ├── budget.py
│       ├── service_slo.py
│       ├── security_audit.py
│       └── infrastructure.py
│
├── examples/                        ← deployment-ready starters
│   ├── gcp-cloud-function/
│   ├── aws-lambda/
│   ├── local-dev/                   ← FastAPI demo (dev only)
│   └── payloads/                    ← canonical sample events
│
├── docs/                            ← deeper docs
│   ├── QUICKSTART.md
│   ├── CONFIGURATION.md
│   ├── FEATURES.md
│   ├── SAMPLE_OUTPUT.md
│   ├── ARCHITECTURE.md
│   ├── DEPLOY_GCP.md
│   ├── DEPLOY_AWS.md
│   ├── DEBUG_RUNBOOK.md
│   └── SCENARIOS.md
│
└── tests/
```

---

## Quick start — 5 minutes

> Goal: get a GCP Cloud Function posting Slack messages for your billing
> budget alerts. The same shape works for AWS Lambda.

### 1. Fork the repo and push to your public GitHub

No CI, no special branches. Just fork and push. The library is installed
directly from that URL.

### 2. Copy `examples/gcp-cloud-function/` into a new folder on your laptop

```
my-alerting-function/
├── main.py            (unchanged)
├── requirements.txt   (point at YOUR fork)
├── config.yaml        (edit channels, recipients, thresholds)
└── deploy.sh          (edit PROJECT_ID and topic name)
```

Change the `git+https://...` line in `requirements.txt` to your fork, e.g.

```
git+https://github.com/Tarunrj99/cloud-alert-hub.git@v0.3.1#egg=cloud-alert-hub
functions-framework>=3.5.0
```

### 3. Set one secret

```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
```

### 4. Deploy

```bash
export PROJECT_ID=your-gcp-project
./deploy.sh
```

### 5. Wire the producer

In Cloud Billing → Budgets → **Manage notifications** → **Connect a Pub/Sub
topic** → select the topic the Cloud Function subscribes to. Your Slack
channel will start receiving formatted, deduped alerts.

Full step-by-step, including permissions and troubleshooting, is in
[`docs/DEPLOY_GCP.md`](docs/DEPLOY_GCP.md).

---

## Configuration model

There are **two** YAML files in the whole system, and you only ever edit
one of them:

| File | Lives in | Purpose | Edited by |
| ---- | -------- | ------- | --------- |
| [`src/cloud_alert_hub/bundled_defaults.yaml`](src/cloud_alert_hub/bundled_defaults.yaml) | Inside the package | Safe defaults — everything off | Library maintainers |
| `config.yaml` | Next to your function/lambda | Your overrides | You |

The library deep-merges them at startup: `defaults ← your config ← env vars`.
Any key you don't set is inherited from defaults, so `config.yaml` stays
small and focused.

The top-level sections, all documented inline in
[`config.example.yaml`](config.example.yaml):

```yaml
app:              # environment, cloud tag, global kill-switches
features:         # enabled/disabled per scenario (budget, slo, security, …)
notifications:    # Slack + email backends (secrets via env vars)
routing:          # named routes (channel + recipient lists)
delivery:         # retries, backoff, timeout
state:            # dedupe backend (memory or file)
payload_overrides:# what the event is allowed to override at runtime
ingress_auth:     # local-dev server only
```

Full reference: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

---

## Feature catalog

Every feature is one file in [`src/cloud_alert_hub/features/`](src/cloud_alert_hub/features/).

| Feature | Claims alerts where | Typical sources |
| ------- | ------------------- | --------------- |
| `budget_alerts` | `kind == "budget"` | GCP Cloud Billing, AWS Budgets, Azure Cost Management |
| `service_slo` | `kind == "service"` | Cloud Monitoring uptime, CloudWatch alarms, custom SLO burn rate |
| `security_audit` | `kind == "security"` | SCC findings, CloudTrail, Azure Defender, audit logs |
| `infrastructure_spike` | `kind == "infrastructure"` | CPU/memory/network usage policies |

Enable any subset per deployment:

```yaml
features:
  budget_alerts:        { enabled: true,  thresholds_percent: [50,70,90,100] }
  service_slo:          { enabled: false }
  security_audit:       { enabled: true }
  infrastructure_spike: { enabled: false }
```

Add your own in ~40 lines of Python — see [Extending](#extending).

---

## Deployment recipes

| Cloud | Runtime | Trigger | Folder | Doc |
| ----- | ------- | ------- | ------ | --- |
| GCP   | Cloud Function (2nd gen) | Pub/Sub | [`examples/gcp-cloud-function/`](examples/gcp-cloud-function/) | [`DEPLOY_GCP.md`](docs/DEPLOY_GCP.md) |
| AWS   | Lambda | SNS | [`examples/aws-lambda/`](examples/aws-lambda/) | [`DEPLOY_AWS.md`](docs/DEPLOY_AWS.md) |
| Azure | Function | Event Grid | pattern identical to AWS example; see the adapter | — |
| Local | FastAPI | HTTP | [`examples/local-dev/`](examples/local-dev/) | [`docs/DEBUG_RUNBOOK.md`](docs/DEBUG_RUNBOOK.md) |

Every recipe has the same shape: wrapper + `requirements.txt` + `config.yaml`
+ `deploy.sh`. The wrapper is never more than ~10 lines.

---

## Running many features from one repo

The design is explicit: **one GitHub repo, many deployments**. Each deployment
is a Cloud Function / Lambda / Cloud Run service that imports the same
library but ships a *different* `config.yaml`.

Pattern:

```
billing-alerts-nonprod/    (Pub/Sub: billing-alerts-nonprod)
  └── config.yaml          features.budget_alerts.enabled = true

security-alerts-prod/      (Pub/Sub: security-findings-prod)
  └── config.yaml          features.security_audit.enabled = true

slo-burn-rate/             (Cloud Run, scheduled)
  └── config.yaml          features.service_slo.enabled = true
```

All three pull the same `cloud_alert_hub` code from your GitHub tag. You roll
out a library fix by bumping the tag in `requirements.txt` and redeploying;
no per-function patching.

---

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Run the debug server:

```bash
uvicorn examples.local-dev.app:app --reload
curl -sX POST http://127.0.0.1:8000/ingest/generic \
  -H 'content-type: application/json' \
  -d @examples/payloads/generic-budget-alert.json | jq
```

Or, from Python:

```python
from cloud_alert_hub import run

run({"kind": "budget", "title": "demo", "summary": "hi", "labels": {"threshold_percent": "100"}},
    source="generic",
    config="./config.yaml")
```

---

## Debugging and audit

* Flip `app.debug_mode: true` — every response contains a `debug.trace` block
  showing which feature matched, the dedupe key, the route it picked, and the
  delivery target.
* Flip `app.dry_run: true` — render and log messages, but don't actually send
  to Slack/email.
* Failed deliveries (after all retries) are written to a JSON-Lines file at
  `DEAD_LETTER_FILE_PATH` for audit review.
* `/debug/metrics` (local server) exposes counters for events received,
  suppressed, delivered, and per-channel success/failure.

Step-by-step playbook: [`docs/DEBUG_RUNBOOK.md`](docs/DEBUG_RUNBOOK.md).

---

## Extending

### Add a new feature

1. `src/cloud_alert_hub/features/my_feature.py`:

    ```python
    from ..models import CanonicalAlert
    from .base import Feature, FeatureMatch

    class MyFeature(Feature):
        name = "my_feature"
        def claims(self, alert): return alert.kind == "my_kind"
        def match(self, alert):
            return FeatureMatch(
                feature_name=self.name,
                route_key=self.route_key,
                dedupe_key=f"{alert.cloud}:{alert.project}:{alert.title}",
                dedupe_window_seconds=self.dedupe_window_seconds,
            )
    ```

2. Register it in `src/cloud_alert_hub/features/__init__.py` (`FEATURE_CLASSES`).
3. Add a block to `bundled_defaults.yaml` with `enabled: false`.

That's it — every existing deployment keeps working; new deployments opt in
by setting `features.my_feature.enabled: true` in their `config.yaml`.

### Add a new cloud

1. Drop an adapter under `src/cloud_alert_hub/adapters/your_cloud.py` that maps
   the raw event to `CanonicalAlert`.
2. Add a thin convenience in `api.py` (`handle_your_cloud`).
3. Copy one of the `examples/` folders and adjust the wrapper.

### Add a new notifier

Sub-class nothing; just add a function to `notifiers/` and wire it into
`processor.py`. Existing features don't need to change — the renderer only
needs to know about new message types, not new delivery channels.

---

## Docs index

| Doc | Topic |
| --- | ----- |
| [`QUICKSTART.md`](docs/QUICKSTART.md) | 5-minute end-to-end walkthrough |
| [`CONFIGURATION.md`](docs/CONFIGURATION.md) | Every config key, with examples |
| [`FEATURES.md`](docs/FEATURES.md) | Built-in features and how to add more |
| [`SAMPLE_OUTPUT.md`](docs/SAMPLE_OUTPUT.md) | What a rendered Slack alert looks like, for every severity |
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Design rationale and trade-offs |
| [`DEPLOY_GCP.md`](docs/DEPLOY_GCP.md) | GCP Cloud Function runbook |
| [`DEPLOY_AWS.md`](docs/DEPLOY_AWS.md) | AWS Lambda runbook |
| [`DEBUG_RUNBOOK.md`](docs/DEBUG_RUNBOOK.md) | Debug mode + investigation checklist + smoke-test recipes |
| [`SCENARIOS.md`](docs/SCENARIOS.md) | Catalog of supported alert scenarios |
| [`examples/README.md`](examples/README.md) | Index of deployment starters |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev setup, PR checklist, commit style |
| [`SECURITY.md`](SECURITY.md) | Supported versions & disclosure policy |
| [`CHANGELOG.md`](CHANGELOG.md) | Release notes |

---

## Contributing

PRs and issues are very welcome. The short version:

1. Fork the repo and create a feature branch.
2. `make venv && make test && make lint` — everything must be green.
3. If you add a new feature, also add a test under `tests/` and, where
   relevant, an entry in [`docs/FEATURES.md`](docs/FEATURES.md) and
   [`docs/SCENARIOS.md`](docs/SCENARIOS.md).
4. Open a PR against `main` with a clear title and a link to the scenario
   or bug you're fixing.

Full checklist, coding conventions, and release process live in
[`CONTRIBUTING.md`](CONTRIBUTING.md). A community-friendly code of conduct
is in [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---

## Security

The library is designed so no secrets ever live in `config.yaml`: Slack
webhooks, SMTP passwords, and ingress tokens are always read from environment
variables that the config *names*. If you find a security issue, please do
**not** open a public issue — follow the disclosure process in
[`SECURITY.md`](SECURITY.md).

---

## License

MIT — see [`LICENSE`](LICENSE). Use it freely inside your organisation or
as the base for your own alerting layer. Attribution is appreciated but not
required.
