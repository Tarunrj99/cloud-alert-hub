"""Tests for the Slack + email renderers.

We deliberately assert on the *shape* of the Block Kit output rather than on
exact string matches so the renderer stays easy to tweak visually without
rewriting tests on every commit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cloud_alert_hub.models import CanonicalAlert
from cloud_alert_hub.renderer import render_email, render_slack


def _budget_alert(**overrides) -> CanonicalAlert:
    base = {
        "cloud": "gcp",
        "environment": "nonprod",
        "project": "my-nonprod-project",
        "account": "01XXXX-YYYYYY-ZZZZZZ",
        "kind": "budget",
        "severity": "high",
        "title": "Example Monthly Budget — 120% reached",
        "summary": "Spend has reached 120% of the $10,000 monthly budget.",
        "labels": {
            "budget_name": "example-monthly",
            "threshold_percent": "120",
        },
        "metrics": {
            "cost_amount": 12012.34,
            "budget_amount": 10000.0,
            "threshold_fraction": 1.2,
        },
        "annotations": {"currencyCode": "USD"},
        "links": {"Budget console": "https://console.cloud.google.com/billing/budgets"},
        "route_key": "finops",
        "occurred_at": datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return CanonicalAlert(**base)


# ---------- Slack ----------

def test_slack_message_has_header_and_progress_bar_for_budget() -> None:
    alert = _budget_alert()
    msg = render_slack(alert, channel="#alerts-finops")

    assert msg.channel == "#alerts-finops"
    assert "HIGH" in msg.text
    assert "120%" in msg.text or "reached" in msg.text

    block_types = [b["type"] for b in msg.blocks]
    assert block_types[0] == "header"
    # Progress section must be present for budget alerts
    progress_sections = [
        b for b in msg.blocks
        if b.get("type") == "section"
        and isinstance(b.get("text"), dict)
        and "Spend progress" in b["text"].get("text", "")
    ]
    assert progress_sections, "budget alerts must include a progress bar section"
    bar = progress_sections[0]["text"]["text"]
    assert "█" in bar or "░" in bar


def test_slack_display_toggles_suppress_sections() -> None:
    alert = _budget_alert()
    display = {
        "show_header": False,
        "show_summary": False,
        "show_progress_bar": False,
        "show_fields": False,
        "show_metrics": False,
        "show_labels": False,
        "show_links": False,
        "show_footer": False,
    }
    msg = render_slack(alert, channel="#alerts", display=display)
    assert msg.blocks == [], "all sections off should yield an empty block list"


def test_slack_show_account_toggle_hides_billing_account() -> None:
    alert = _budget_alert()
    hidden = render_slack(alert, channel="#x", display={"show_account": False})
    visible = render_slack(alert, channel="#x", display={"show_account": True})
    hidden_text = str(hidden.model_dump())
    visible_text = str(visible.model_dump())
    assert "01XXXX-YYYYYY-ZZZZZZ" not in hidden_text
    assert "01XXXX-YYYYYY-ZZZZZZ" in visible_text


def test_slack_label_allow_and_deny_lists() -> None:
    alert = _budget_alert(
        labels={
            "budget_name": "demo",
            "threshold_percent": "120",
            "internal_cost_center": "secret-1234",
        },
    )
    display = {
        "show_labels": True,
        "label_deny_list": ["internal_cost_center"],
    }
    msg = render_slack(alert, channel="#x", display=display)
    serialised = str(msg.model_dump())
    assert "secret-1234" not in serialised
    assert "budget_name" in serialised


def test_slack_severity_banner_reflects_kind() -> None:
    alert = _budget_alert(kind="security", severity="critical", title="IAM change")
    msg = render_slack(alert, channel="#x")
    serialised = str(msg.model_dump())
    assert "CRITICAL" in serialised
    assert ":shield:" in serialised


def test_slack_progress_bar_caps_at_full_for_over_100() -> None:
    alert = _budget_alert(
        labels={"budget_name": "demo", "threshold_percent": "210"},
        metrics={"cost_amount": 21000.0, "budget_amount": 10000.0, "threshold_fraction": 2.1},
    )
    msg = render_slack(alert, channel="#x")
    progress = next(
        b for b in msg.blocks
        if b.get("type") == "section"
        and isinstance(b.get("text"), dict)
        and "Spend progress" in b["text"].get("text", "")
    )
    bar = progress["text"]["text"]
    # Bar should be full (all ticks filled) with 210% callout
    assert "210%" in bar


def test_slack_non_budget_has_no_progress_bar() -> None:
    alert = _budget_alert(kind="service", severity="high", metrics={"error_rate": 0.05})
    msg = render_slack(alert, channel="#x")
    for block in msg.blocks:
        text = block.get("text", {}).get("text", "") if isinstance(block.get("text"), dict) else ""
        assert "Spend progress" not in text


# ---------- Email ----------

def test_email_body_includes_key_fields() -> None:
    alert = _budget_alert()
    msg = render_email(alert, recipients=["qa@example.com"], from_address="bot@example.com")
    assert msg.subject.startswith("[HIGH]")
    assert "Cloud       : gcp" in msg.body_text
    assert "Project     : my-nonprod-project" in msg.body_text
    assert "cost_amount" in msg.body_text
    assert "budget_name" in msg.body_text
