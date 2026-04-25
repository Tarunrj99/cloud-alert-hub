"""End-to-end smoke tests against the public API.

Uses dry_run mode so no real HTTP calls happen.
"""

from __future__ import annotations

import json

from cloud_alert_hub import handle_aws_sns, handle_gcp_pubsub, load_config, run


def _dry_run_config(feature: str = "budget_alerts") -> dict:
    return {
        "app": {
            "environment": "test", "cloud": "gcp",
            "alerting_enabled": True, "dry_run": True, "debug_mode": True,
            "manifest": {"enabled": False},  # tests must be hermetic — no upstream fetch
        },
        "features": {feature: {"enabled": True}},
        "notifications": {
            "slack": {"enabled": True, "webhook_url_env": "SLACK_WEBHOOK_URL_TEST", "default_channel": "#test"},
            "email": {"enabled": True, "provider": "stdout"},
        },
        "routing": {
            "default_route": "finops",
            "routes": {
                "finops": {"slack_channel": "#test-finops", "email_recipients": ["qa@example.com"]},
                "security": {"slack_channel": "#test-sec", "email_recipients": []},
            },
        },
    }


def test_run_generic_budget_dry_run() -> None:
    payload = {
        "cloud": "gcp",
        "environment": "test",
        "project": "demo",
        "kind": "budget",
        "severity": "high",
        "title": "Budget 100%",
        "summary": "Test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    result = run(payload, source="generic", config=_dry_run_config())
    assert result["status"] == "processed"
    assert result["route_key"] == "finops"
    assert result["deliveries"]["slack"]["status"] == "dry_run"
    assert "debug" in result
    assert result["debug"]["trace"]["matched_feature"] == "budget_alerts"


def test_run_no_feature_claimed_is_suppressed() -> None:
    payload = {"cloud": "gcp", "kind": "unknown_kind", "title": "x", "summary": "y"}
    result = run(payload, source="generic", config=_dry_run_config())
    assert result["status"] == "suppressed"
    assert result["reason"] == "no_feature_claimed"


def test_handle_gcp_pubsub_envelope() -> None:
    import base64

    inner = {
        "kind": "budget",
        "severity": "high",
        "title": "GCP 100%",
        "summary": "from pubsub",
        "project_id": "demo",
        "environment": "test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    envelope = {
        "message": {
            "data": base64.b64encode(json.dumps(inner).encode("utf-8")).decode("ascii"),
            "attributes": {"environment": "test"},
        },
        "subscription": "projects/demo/subscriptions/x",
    }
    result = handle_gcp_pubsub(envelope, config=_dry_run_config())
    assert result["status"] == "processed"
    assert result["deliveries"]["slack"]["status"] == "dry_run"


def test_handle_aws_sns_record() -> None:
    sns_event = {
        "Records": [
            {
                "EventSource": "aws:sns",
                "Sns": {
                    "Subject": "Budget 50%",
                    "Message": json.dumps(
                        {
                            "kind": "budget",
                            "severity": "medium",
                            "title": "AWS 50%",
                            "summary": "from sns",
                            "account_id": "123",
                            "labels": {"budget_name": "demo", "threshold_percent": "50"},
                        }
                    ),
                },
            }
        ]
    }
    result = handle_aws_sns(sns_event, config=_dry_run_config())
    assert result["status"] == "processed"


def test_load_config_merges_defaults_with_user_dict() -> None:
    cfg = load_config({"app": {"environment": "qa"}})
    assert cfg.environment == "qa"
    assert cfg.default_route == "finops"
    assert "budget_alerts" in (cfg.get("features", default={}) or {})


def test_disabled_alerting_kills_delivery() -> None:
    cfg = _dry_run_config()
    cfg["app"]["alerting_enabled"] = False
    payload = {"kind": "budget", "title": "x", "summary": "y", "labels": {"threshold_percent": "100"}}
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "suppressed"
    assert result["reason"] == "global_alerting_disabled"


def _native_gcp_budget_envelope() -> dict:
    """Synthesizes a Pub/Sub envelope shaped exactly like Cloud Billing emits.

    Crucially, it carries NO ``environment`` or ``project_id`` attribute — the
    real GCP Billing service doesn't include them. The pipeline must backfill
    these from operator config so renderers don't show ``unknown``.
    """
    import base64

    native_budget = {
        "budgetDisplayName": "Demo Monthly Budget",
        "alertThresholdExceeded": 1.0,
        "costAmount": 10000,
        "budgetAmount": 10000,
        "currencyCode": "USD",
        "costIntervalStart": "2026-04-01T00:00:00Z",
        "budgetAmountType": "SPECIFIED_AMOUNT",
    }
    return {
        "message": {
            "data": base64.b64encode(json.dumps(native_budget).encode("utf-8")).decode("ascii"),
            "attributes": {"billingAccountId": "01ABCD-EFGH-IJKL"},
        },
    }


def test_native_gcp_budget_inherits_environment_from_config() -> None:
    cfg = _dry_run_config()
    cfg["app"]["environment"] = "nonprod"
    cfg["app"]["cloud"] = "gcp"
    result = handle_gcp_pubsub(_native_gcp_budget_envelope(), config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["environment"] == "nonprod"
    assert result["debug"]["alert"]["cloud"] == "gcp"


def test_native_gcp_budget_inherits_project_from_app_config() -> None:
    cfg = _dry_run_config()
    cfg["app"]["project"] = "my-team-nonprod"
    result = handle_gcp_pubsub(_native_gcp_budget_envelope(), config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["project"] == "my-team-nonprod"


def test_native_gcp_budget_falls_back_to_GOOGLE_CLOUD_PROJECT_env_var(monkeypatch) -> None:
    """When app.project is empty (the bundled default), the library should
    auto-detect the project from the runtime env var that Cloud Functions /
    Cloud Run set. This makes deployments work with zero config edits."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "auto-detected-project")
    cfg = _dry_run_config()
    cfg["app"].pop("project", None)
    result = handle_gcp_pubsub(_native_gcp_budget_envelope(), config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["project"] == "auto-detected-project"


def test_explicit_environment_in_payload_wins_over_config() -> None:
    """If the upstream payload explicitly sets environment, config must not override it."""
    cfg = _dry_run_config()
    cfg["app"]["environment"] = "nonprod"
    payload = {
        "cloud": "gcp",
        "environment": "staging",
        "kind": "budget",
        "title": "Budget 100%",
        "summary": "Test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["environment"] == "staging"


def test_explicit_project_in_payload_wins_over_config(monkeypatch) -> None:
    """A canonical payload with an explicit project_id must not be clobbered
    by either app.project config or the runtime env var fallback."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "should-not-be-used")
    cfg = _dry_run_config()
    cfg["app"]["project"] = "also-should-not-be-used"
    payload = {
        "cloud": "gcp",
        "environment": "nonprod",
        "project": "explicit-from-payload",
        "kind": "budget",
        "title": "Budget 100%",
        "summary": "Test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["project"] == "explicit-from-payload"
