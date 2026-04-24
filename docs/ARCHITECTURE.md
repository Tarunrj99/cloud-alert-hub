# Architecture

## Goals

1. **Cloud-neutral core.** Policy, rendering, retries, dedupe, and audit
   behaviour must be identical regardless of whether the event came from
   GCP, AWS, or Azure.
2. **Single library, many deployments.** The same artifact is installed as a
   dependency into Cloud Functions, Lambdas, Cloud Run, and the local dev
   server. The only deployment-specific file is `config.yaml`.
3. **Audit-friendly.** Every delivery decision (match, dedupe, suppress,
   retry, dead-letter) is traceable from logs alone.
4. **Minimal config surface.** Two YAML files: the bundled defaults shipped
   with the library and your deployment's overrides. No environment-folder
   forests.

## Request lifecycle

```
 raw cloud event
      │
      ▼
┌─────────────┐  cloud-specific only here
│  adapter    │  (gcp_pubsub / aws_sns / azure_eventgrid / generic)
└──────┬──────┘
       │  CanonicalAlert
       ▼
┌─────────────┐  safe overrides applied (route_key, labels, ...)
│  policy     │  features[].claims() → first match wins
└──────┬──────┘  dedupe state consulted
       │  PolicyDecision (should_deliver, target, trace)
       ▼
┌─────────────┐  render Slack Block Kit + email body
│  renderer   │
└──────┬──────┘
       │  SlackMessage / EmailMessage
       ▼
┌─────────────┐  per-channel retry with backoff
│  notifier   │  → Slack webhook · email provider
└──────┬──────┘
       │
       ▼
┌─────────────┐  on failure after all retries
│ dead-letter │  JSON-Lines file for audit replay
└─────────────┘
```

## Key abstractions

### `CanonicalAlert` (models.py)

Pydantic model every adapter produces. Includes `cloud`, `environment`,
`project`, `service`, `kind`, `severity`, `labels`, `metrics`, and the
original `source_payload` for debugging.

### `Config` (config.py)

Immutable view over the merged YAML + env overrides. Exposes every setting
through typed properties so callers don't touch raw dicts.

### `Feature` (features/base.py)

Abstract base class. A feature is `claims(alert) → bool` plus
`match(alert) → FeatureMatch`. The registry in `features/__init__.py` is the
only place that knows about concrete features.

### `BaseState` (state.py)

Deduplication contract: `should_suppress(key, window_seconds) → bool`. Two
built-in backends (in-memory for stateless runtimes, file for servers); add
Redis / Firestore / DynamoDB by subclassing.

### `AlertProcessor` (processor.py)

Glue. Evaluates the policy, renders messages, calls notifiers with retries,
records metrics, writes dead-letter entries. Cloud- and
deployment-independent.

### Notifiers (notifiers/*.py)

Thin wrappers around delivery channels. Each notifier returns a status dict
(`sent`, `failed`, `dry_run`, `skipped`, `error`) the processor uses to
decide on retry vs. dead-letter.

## Why features instead of YAML rule lists

The previous iteration of this template had all routing rules in
`configs/rules.yaml`. That worked for simple cases but quickly became:

* **Opaque** — rule behaviour depended on template interpolation and
  implicit ordering.
* **Untestable** — rules weren't Python, so you couldn't pytest them.
* **Monolithic** — one big file for every scenario across every team.

Turning each scenario into a Python class solved all three:

| Axis | Rule file | Feature class |
| ---- | --------- | ------------- |
| Per-scenario tests | hard | natural (`test_budget_feature.py`) |
| Inheritance / reuse | none | standard Python |
| Type checking | none | mypy / pyright |
| Config surface | big YAML | thin: `enabled`, `route`, `dedupe_window_seconds`, plus feature-specific knobs |

Operators still edit YAML, but the YAML is small and declarative — "is this
feature on?" — while the logic lives in code.

## Why the library is shipped, not the server

Cloud Functions and Lambdas are the natural fit for event-driven alerting
(pay per invocation, scale to zero, no long-lived state to babysit). If the
template only shipped an HTTP server you'd need to deploy *that* somewhere,
secure it, keep it running, monitor it — a lot of operations for something
that is fundamentally stateless.

Shipping a Python library instead lets you:

* Reuse the provider's own auth (Pub/Sub push identity, EventBridge resource
  policies).
* Scale with the upstream topic, not with a babysat service.
* Deploy N specialised functions that each pull from the same library
  version, keeping blast radius small.

The FastAPI dev server exists only to support local iteration and automated
tests; it deliberately shares no runtime state with production deployments.

## Trade-offs and deferred work

* **State backends.** File-based dedupe is fine for a single-replica server
  but not for horizontally scaled workers. Redis / Firestore backends are
  straightforward to add behind `BaseState`.
* **Email providers.** Only `stdout` is wired up; real SES / SendGrid / SMTP
  integrations are one small function each in `notifiers/email.py`.
* **Schema evolution.** Config is validated leniently (missing keys fall
  back to defaults). Consider adding JSONSchema or Pydantic validation for
  stricter deployments.
* **Multi-feature per alert.** Today the first claiming feature wins. Fan-
  out to multiple features is a ~10-line change in `policy.evaluate_policy`.
