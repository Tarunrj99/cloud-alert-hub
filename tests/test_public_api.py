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
