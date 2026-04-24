# Security Policy

## Supported versions

`cloud-alert-hub` is currently in **beta**. Only the latest tagged release on
`main` receives security fixes.

| Version | Supported |
| ------- | --------- |
| `0.1.x` | ✅ |
| `< 0.1` | ❌ |

## Reporting a vulnerability

**Please do not open a public GitHub issue** for security problems. Instead,
use one of the following channels:

1. **GitHub Security Advisories** (preferred) — open a private advisory at
   <https://github.com/Tarunrj99/cloud-alert-hub/security/advisories/new>.
2. **Direct email** — send the details to the maintainer listed in
   [`pyproject.toml`](pyproject.toml) (`[project].authors`).

Please include:

- A description of the vulnerability and its impact.
- A minimal reproducer (config snippet, payload, and the expected vs. actual
  behavior).
- The version/commit you tested against.
- Your preferred contact and attribution style if you'd like to be credited.

## What to expect

- **Acknowledgement** within 72 hours.
- **Triage** within 7 days, including whether it's in scope and a severity
  rating.
- **Fix or mitigation**:
  - High severity: targeted patch release within ~2 weeks.
  - Medium: bundled into the next minor release.
  - Low: addressed opportunistically in `main`.
- **Disclosure**: coordinated — we'll agree on a public disclosure date
  together, typically ≤ 30 days after a fix ships.

## Scope

In scope:

- Vulnerabilities in the `cloud_alert_hub` Python package (policy engine,
  renderers, notifiers, adapters, config loader).
- Example deployment scripts in `examples/` that could leak secrets or grant
  unintended permissions when used as documented.

Out of scope:

- Third-party services the library integrates with (Slack, SMTP, cloud
  platforms) — report those to their respective vendors.
- Issues that require an attacker to already have administrator-level
  access to the deployment target.
- Denial of service caused by an operator configuring unbounded retries,
  thresholds, or notification volumes.

## Secrets handling — design summary

By design, `cloud-alert-hub` keeps secrets **out of config files**:

- Slack webhook URLs are read from the environment variable named by
  `notifications.slack.webhook_url_env` (default `SLACK_WEBHOOK_URL`).
- SMTP credentials are read from env vars named by the config.
- The local dev server's ingress token is read from the env var named by
  `ingress_auth.token_env`.

If you find a code path that logs secrets, persists them to the dead-letter
file, or includes them in alert payloads, please report it through the
channels above.
