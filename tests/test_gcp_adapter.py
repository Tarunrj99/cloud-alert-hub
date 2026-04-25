"""Tests for the GCP Pub/Sub adapter.

Covers the three input shapes the adapter must recognise:
    * native Cloud Billing Budget notification
    * native Cloud Monitoring incident notification
    * a canonical (user-defined) payload
"""

from __future__ import annotations

import base64
import json

from cloud_alert_hub.adapters.gcp_pubsub import from_gcp_pubsub


def _envelope(inner: dict, attrs: dict | None = None) -> dict:
    return {
        "message": {
            "data": base64.b64encode(json.dumps(inner).encode()).decode(),
            "attributes": attrs or {},
            "messageId": "test-id",
            "publishTime": "2026-04-25T00:00:00Z",
        },
        "subscription": "projects/demo/subscriptions/x",
    }


def test_native_billing_budget_payload_is_parsed() -> None:
    inner = {
        "budgetDisplayName": "Example Monthly Budget",
        "budgetAmount": 10000.0,
        "costAmount": 5023.18,
        "currencyCode": "USD",
        "alertThresholdExceeded": 0.5,
        "costIntervalStart": "2026-04-01T00:00:00Z",
        "budgetAmountType": "SPECIFIED_AMOUNT",
    }
    attrs = {
        "billingAccountId": "01XXXX-YYYYYY-ZZZZZZ",
        "budgetId": "00000000-0000-0000-0000-000000000000",
        "schemaVersion": "1.0",
    }
    alert = from_gcp_pubsub(_envelope(inner, attrs))

    assert alert.kind == "budget"
    assert alert.cloud == "gcp"
    assert alert.account == "01XXXX-YYYYYY-ZZZZZZ"
    assert "Example Monthly Budget" in alert.title
    assert "50%" in alert.title
    assert alert.labels["budget_name"] == "Example Monthly Budget"
    assert alert.labels["threshold_percent"] == "50"
    assert alert.metrics["cost_amount"] == 5023.18
    assert alert.metrics["budget_amount"] == 10000.0
    assert alert.metrics["threshold_fraction"] == 0.5
    assert "console.cloud.google.com/billing" in next(iter(alert.links.values()))
    assert alert.labels["currency"] == "USD"
    assert alert.labels["budget_amount_type"] == "SPECIFIED_AMOUNT"
    assert alert.labels["budget_amount_type_label"] == "Specified amount"
    assert alert.labels["period_label"] == "April 2026"
    # Spend ratio (50.23%) is within 5pp of the threshold (50%), so the
    # summary uses the simple form (no "(crossed X%)" parenthetical).
    assert alert.metrics["actual_percent"] == 50
    assert alert.labels["actual_percent"] == "50"
    assert "Spend has reached" in alert.summary
    assert "*50%*" in alert.summary


def test_native_budget_summary_shows_actual_percent_when_over_threshold() -> None:
    """When spend has drifted well past the highest crossed threshold (e.g.
    you crossed 300% but you're already at 371%), the summary must show
    *both* numbers so the reader doesn't read "300%" as the current spend.
    """
    inner = {
        "budgetDisplayName": "Example Monthly Budget",
        "budgetAmount": 10000.0,
        "costAmount": 37068.59,
        "currencyCode": "USD",
        "alertThresholdExceeded": 3.0,  # crossed the 300% step
        "costIntervalStart": "2026-04-01T07:00:00Z",
        "budgetAmountType": "SPECIFIED_AMOUNT",
    }
    alert = from_gcp_pubsub(_envelope(inner))
    assert alert.labels["threshold_percent"] == "300"
    assert alert.metrics["actual_percent"] == 371
    assert alert.labels["actual_percent"] == "371"
    # Title is unambiguous: "300% threshold reached", not "300% reached".
    assert "300% threshold reached" in alert.title
    # Summary references both the threshold and the actual ratio.
    assert "Crossed the *300%* budget threshold" in alert.summary
    assert "*371%* of budget" in alert.summary
    assert "$37,068.59" in alert.summary
    assert "$10,000.00" in alert.summary


def test_native_budget_period_label_for_mid_month_start() -> None:
    inner = {
        "budgetDisplayName": "weird",
        "budgetAmount": 100.0,
        "costAmount": 50.0,
        "currencyCode": "USD",
        "alertThresholdExceeded": 0.5,
        "costIntervalStart": "2026-04-15T00:00:00Z",
        "budgetAmountType": "LAST_PERIODS_AMOUNT",
    }
    alert = from_gcp_pubsub(_envelope(inner))
    assert alert.labels["period_label"] == "from 2026-04-15"
    assert alert.labels["budget_amount_type_label"] == "Last period's amount"


def test_native_budget_severity_maps_to_percent() -> None:
    def sev(fraction: float) -> str:
        alert = from_gcp_pubsub(
            _envelope(
                {
                    "budgetDisplayName": "b",
                    "budgetAmount": 100,
                    "costAmount": 100 * fraction,
                    "alertThresholdExceeded": fraction,
                }
            )
        )
        return alert.severity

    assert sev(0.5) == "low"
    assert sev(0.9) == "medium"
    assert sev(1.2) == "high"
    assert sev(2.1) == "critical"


def test_monitoring_incident_payload_is_parsed() -> None:
    inner = {
        "version": "1.2",
        "incident": {
            "incident_id": "abc",
            "scoping_project_id": "my-prod-project",
            "resource_type_display_name": "Cloud Run Revision",
            "policy_name": "Error rate too high",
            "condition_name": "5xx > 5%",
            "state": "open",
            "summary": "Error rate 12% for Cloud Run",
            "url": "https://console.cloud.google.com/monitoring/alerting/incidents/abc",
        },
    }
    alert = from_gcp_pubsub(_envelope(inner))
    assert alert.kind == "service"
    assert alert.severity == "critical"
    assert "Error rate too high" in alert.title
    assert "5xx > 5%" in alert.title
    assert alert.labels["state"] == "open"
    assert alert.project == "my-prod-project"
    assert "Monitoring incident" in alert.links


def test_canonical_payload_still_works() -> None:
    inner = {
        "kind": "budget",
        "severity": "high",
        "title": "Canonical shape",
        "summary": "yes",
        "project_id": "demo",
        "labels": {"budget_name": "x", "threshold_percent": "100"},
    }
    alert = from_gcp_pubsub(_envelope(inner, {"environment": "qa"}))
    assert alert.kind == "budget"
    assert alert.severity == "high"
    assert alert.title == "Canonical shape"
    assert alert.environment == "qa"


def test_bare_message_without_envelope_is_accepted() -> None:
    inner = {"budgetDisplayName": "b", "alertThresholdExceeded": 1.0, "budgetAmount": 100, "costAmount": 100}
    bare = {
        "data": base64.b64encode(json.dumps(inner).encode()).decode(),
        "attributes": {},
    }
    alert = from_gcp_pubsub(bare)
    assert alert.kind == "budget"
    assert alert.labels["threshold_percent"] == "100"
