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
        "show_budget_details": False,
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


def test_slack_progress_bar_shows_actual_spend_when_drifted_past_threshold() -> None:
    """Regression: when GCP keeps re-emitting "300% reached" but spend is
    actually at 371%, the progress bar must show 371% and surface the
    crossed threshold separately. Otherwise readers misread the alert as
    "spend equals 300%".
    """
    alert = _budget_alert(
        labels={"budget_name": "demo", "threshold_percent": "300"},
        metrics={
            "cost_amount": 37068.59,
            "budget_amount": 10000.0,
            "threshold_fraction": 3.0,
        },
    )
    msg = render_slack(alert, channel="#x")
    progress = next(
        b for b in msg.blocks
        if b.get("type") == "section"
        and isinstance(b.get("text"), dict)
        and "Spend progress" in b["text"].get("text", "")
    )
    text = progress["text"]["text"]
    assert "371%" in text
    assert "crossed *300%* threshold" in text


def test_slack_non_budget_has_no_progress_bar() -> None:
    alert = _budget_alert(kind="service", severity="high", metrics={"error_rate": 0.05})
    msg = render_slack(alert, channel="#x")
    for block in msg.blocks:
        text = block.get("text", {}).get("text", "") if isinstance(block.get("text"), dict) else ""
        assert "Spend progress" not in text


# ---------- Email ----------

def test_slack_header_includes_environment_by_default() -> None:
    alert = _budget_alert(environment="nonprod")
    msg = render_slack(alert, channel="#x")
    header = msg.blocks[0]
    assert header["type"] == "header"
    assert "nonprod" in header["text"]["text"]
    assert "[HIGH · nonprod]" in header["text"]["text"]


def test_slack_header_hides_environment_when_toggled() -> None:
    alert = _budget_alert(environment="nonprod")
    msg = render_slack(alert, channel="#x", display={"show_environment_in_header": False})
    header = msg.blocks[0]
    assert "nonprod" not in header["text"]["text"]
    assert header["text"]["text"].startswith("[HIGH]")


def test_slack_budget_details_section_shows_for_budget_kind() -> None:
    alert = _budget_alert(
        labels={
            "budget_name": "example-monthly",
            "threshold_percent": "120",
            "currency": "USD",
            "budget_amount_type_label": "Specified amount",
            "period_label": "April 2026",
        },
    )
    msg = render_slack(alert, channel="#x")
    serialised = str(msg.model_dump())
    assert "Budget name" in serialised
    assert "example-monthly" in serialised
    assert "April 2026" in serialised
    assert "Specified amount" in serialised
    assert "Budget amount" in serialised
    assert "Spent so far" in serialised


def test_slack_budget_details_remaining_when_under_budget() -> None:
    alert = _budget_alert(
        severity="medium",
        title="demo 90%",
        metrics={"cost_amount": 9000.0, "budget_amount": 10000.0, "threshold_fraction": 0.9},
        labels={"budget_name": "demo", "threshold_percent": "90", "currency": "USD",
                "period_label": "April 2026"},
    )
    msg = render_slack(alert, channel="#x")
    serialised = str(msg.model_dump())
    assert "Remaining" in serialised
    assert "$1,000.00" in serialised
    assert "Over budget" not in serialised


def test_slack_budget_details_overage_when_over_budget() -> None:
    alert = _budget_alert(
        title="demo 120%",
        metrics={"cost_amount": 12000.0, "budget_amount": 10000.0, "threshold_fraction": 1.2},
        labels={"budget_name": "demo", "threshold_percent": "120", "currency": "USD",
                "period_label": "April 2026"},
    )
    msg = render_slack(alert, channel="#x")
    serialised = str(msg.model_dump())
    assert "Over budget" in serialised
    assert "$2,000.00" in serialised
    assert "Remaining" not in serialised


def test_slack_budget_details_hidden_by_toggle() -> None:
    alert = _budget_alert()
    msg = render_slack(alert, channel="#x", display={"show_budget_details": False})
    serialised = str(msg.model_dump())
    assert "Budget name" not in serialised
    assert "Billing period" not in serialised


def test_slack_budget_details_skipped_for_non_budget() -> None:
    alert = _budget_alert(kind="service", title="error rate high", severity="high")
    msg = render_slack(alert, channel="#x")
    serialised = str(msg.model_dump())
    assert "Budget name" not in serialised
    assert "Billing period" not in serialised


def _spike_alert(**overrides) -> CanonicalAlert:
    base = {
        "cloud": "gcp",
        "environment": "nonprod",
        "project": "my-nonprod-project",
        "service": "Generative Language API",
        "kind": "cost_spike",
        "severity": "critical",
        "title": "Cost spike — Generative Language API",
        "summary": "Generative Language API spend jumped from $48/day to $5,021 today.",
        "labels": {
            "service": "Generative Language API",
            "spike_period": "2026-04-21",
        },
        "metrics": {
            "previous_amount": 48.13,
            "current_amount": 5021.44,
            "delta_percent": 10333.0,
        },
        "annotations": {"currencyCode": "USD"},
        "route_key": "finops",
        "occurred_at": datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return CanonicalAlert(**base)


def test_slack_spike_details_block_shows_baseline_current_delta() -> None:
    msg = render_slack(_spike_alert(), channel="#x")
    serialised = str(msg.model_dump())
    assert "Service" in serialised
    assert "Baseline" in serialised
    assert "$48.13" in serialised
    assert "Current" in serialised
    assert "$5,021.44" in serialised
    # +10333% should pick up the fire emoji because delta >= 1000
    assert "+10,333%" in serialised
    assert "fire" in serialised


def test_slack_spike_details_skipped_for_non_spike_kind() -> None:
    alert = _budget_alert(kind="budget")
    msg = render_slack(alert, channel="#x")
    serialised = str(msg.model_dump())
    assert "Baseline" not in serialised


def test_slack_spike_details_hidden_by_toggle() -> None:
    msg = render_slack(_spike_alert(), channel="#x", display={"show_spike_details": False})
    serialised = str(msg.model_dump())
    assert "Baseline" not in serialised


def test_email_body_includes_key_fields() -> None:
    alert = _budget_alert()
    msg = render_email(alert, recipients=["qa@example.com"], from_address="bot@example.com")
    assert msg.subject.startswith("[HIGH]")
    assert "Cloud       : gcp" in msg.body_text
    assert "Project     : my-nonprod-project" in msg.body_text
    assert "cost_amount" in msg.body_text
    assert "budget_name" in msg.body_text
