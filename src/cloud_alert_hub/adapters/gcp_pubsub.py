"""GCP Pub/Sub adapter.

Handles three shapes you'll see in practice:

1.  **Native Cloud Billing Budget** notification payload — has
    ``budgetDisplayName`` / ``alertThresholdExceeded`` / ``costAmount`` /
    ``budgetAmount``. Emitted by Cloud Billing when it hits a configured
    threshold and publishes to its Pub/Sub topic.

2.  **Native Cloud Monitoring alert** notification payload — has an
    ``incident`` dict with ``policy_name``, ``condition_name``, ``state``.
    Emitted when a monitoring alert policy is wired to a Pub/Sub notification
    channel.

3.  **Canonical** (your own producers): a dict that already carries
    ``title`` / ``summary`` / ``severity`` / ``kind`` / ``labels``.

Pub/Sub itself delivers the message two ways:

* **Background / 1st-gen Cloud Functions**: platform hands you the decoded
  message dict directly (``{"data": "<b64>", "attributes": {...}}``).
* **2nd-gen Cloud Functions / Cloud Run / HTTP push**: wrapped in an envelope
  (``{"message": {"data": "<b64>", ...}, "subscription": ...}``).

Either is accepted; callers don't need to pre-normalize.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from ..models import CanonicalAlert


_AMOUNT_TYPE_LABELS = {
    "SPECIFIED_AMOUNT": "Specified amount",
    "LAST_PERIODS_AMOUNT": "Last period's amount",
}


def _format_period_label(cost_interval_start: str | None) -> str | None:
    """Turn the ``costIntervalStart`` ISO timestamp into a short period label.

    Examples:
        ``2026-04-01T00:00:00Z`` → ``"April 2026"`` (start of a calendar month)
        ``2026-04-15T00:00:00Z`` → ``"from 2026-04-15"`` (mid-month start)

    We deliberately don't try to *guess* whether the budget is monthly /
    quarterly / yearly — the Pub/Sub payload doesn't carry that information.
    Operators should convey the period cadence in the budget's display name.
    """
    if not cost_interval_start:
        return None
    try:
        dt = datetime.fromisoformat(cost_interval_start.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.day == 1:
        return dt.strftime("%B %Y")
    return f"from {dt.strftime('%Y-%m-%d')}"


def _decode_data(data: str | None) -> dict[str, Any]:
    if not data:
        return {}
    try:
        raw = base64.b64decode(data).decode("utf-8")
    except (ValueError, TypeError):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_text": raw}
    return parsed if isinstance(parsed, dict) else {}


def _severity_for_budget(threshold_fraction: float) -> str:
    """Map the ``alertThresholdExceeded`` fraction to a severity level.

    The policy engine will later re-evaluate via the budget feature, but we
    give the renderer a sensible starting severity so dry-run/error paths are
    still nicely coloured.
    """
    pct = threshold_fraction * 100
    if pct >= 200:
        return "critical"
    if pct >= 100:
        return "high"
    if pct >= 90:
        return "medium"
    if pct >= 50:
        return "low"
    return "info"


def _looks_like_native_budget(decoded: dict[str, Any]) -> bool:
    return "budgetDisplayName" in decoded or "alertThresholdExceeded" in decoded


def _looks_like_monitoring_incident(decoded: dict[str, Any]) -> bool:
    incident = decoded.get("incident")
    return isinstance(incident, dict) and "condition_name" in incident


def _format_currency(amount: float | int | None, currency: str | None) -> str:
    if amount is None:
        return "n/a"
    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get((currency or "").upper(), "")
    return f"{sym}{amount_f:,.2f}" + (f" {currency}" if not sym and currency else "")


def _from_native_budget(
    decoded: dict[str, Any], attrs: dict[str, Any]
) -> CanonicalAlert:
    budget_name = decoded.get("budgetDisplayName") or "GCP Budget"
    budget_amount = decoded.get("budgetAmount")
    cost_amount = decoded.get("costAmount")
    currency = decoded.get("currencyCode") or "USD"
    threshold_fraction = float(decoded.get("alertThresholdExceeded") or 0)
    threshold_percent = int(round(threshold_fraction * 100))

    cost_fmt = _format_currency(cost_amount, currency)
    budget_fmt = _format_currency(budget_amount, currency)

    # Compute the *actual* spend ratio so the summary is unambiguous. GCP
    # Cloud Billing keeps re-publishing "300% threshold reached" messages
    # even when actual spend has grown well past 300%, so just echoing
    # ``threshold_percent`` reads as "spend = 300%" — misleading once you're
    # over the highest configured threshold.
    actual_percent: int | None = None
    if (
        isinstance(cost_amount, (int, float))
        and isinstance(budget_amount, (int, float))
        and budget_amount
    ):
        actual_percent = int(round(float(cost_amount) / float(budget_amount) * 100))

    title = f"{budget_name} — {threshold_percent}% threshold reached"
    if actual_percent is not None and abs(actual_percent - threshold_percent) >= 5:
        # Spend has drifted noticeably past the configured threshold (e.g. you
        # crossed 300% but you're currently at 371%). Show both numbers.
        summary = (
            f"Crossed the *{threshold_percent}%* budget threshold — "
            f"current spend is {cost_fmt} of {budget_fmt} "
            f"(*{actual_percent}%* of budget)."
        )
    else:
        summary = (
            f"Spend has reached *{threshold_percent}%* of the budget "
            f"({cost_fmt} of {budget_fmt})."
        )

    labels = {
        "budget_name": str(budget_name),
        "threshold_percent": str(threshold_percent),
        "currency": str(currency),
    }
    amount_type_raw = decoded.get("budgetAmountType")
    if amount_type_raw:
        labels["budget_amount_type"] = str(amount_type_raw)
        labels["budget_amount_type_label"] = _AMOUNT_TYPE_LABELS.get(
            str(amount_type_raw), str(amount_type_raw).replace("_", " ").title()
        )
    cost_interval_start = decoded.get("costIntervalStart")
    if cost_interval_start:
        labels["cost_interval_start"] = str(cost_interval_start)
        period_label = _format_period_label(str(cost_interval_start))
        if period_label:
            labels["period_label"] = period_label

    metrics: dict[str, float] = {}
    if isinstance(cost_amount, (int, float)):
        metrics["cost_amount"] = float(cost_amount)
    if isinstance(budget_amount, (int, float)):
        metrics["budget_amount"] = float(budget_amount)
    if threshold_fraction:
        metrics["threshold_fraction"] = threshold_fraction
    if actual_percent is not None:
        metrics["actual_percent"] = float(actual_percent)
        labels["actual_percent"] = str(actual_percent)

    billing_account = attrs.get("billingAccountId")
    links: dict[str, str] = {}
    if billing_account:
        links["Budget console"] = (
            f"https://console.cloud.google.com/billing/{billing_account}/budgets"
        )
    else:
        links["Budget console"] = "https://console.cloud.google.com/billing/budgets"

    return CanonicalAlert(
        cloud="gcp",
        environment=attrs.get("environment", "unknown"),
        project=attrs.get("project_id"),
        account=billing_account,
        kind="budget",
        severity=_severity_for_budget(threshold_fraction),
        title=title,
        summary=summary,
        labels=labels,
        metrics=metrics,
        annotations={
            k: str(v)
            for k, v in decoded.items()
            if k not in {"budgetAmount", "costAmount", "alertThresholdExceeded"}
            and v is not None
        },
        links=links,
        source_payload=decoded,
    )


def _from_monitoring_incident(
    decoded: dict[str, Any], attrs: dict[str, Any]
) -> CanonicalAlert:
    incident = decoded.get("incident") or {}
    policy_name = incident.get("policy_name") or "Cloud Monitoring Policy"
    condition_name = incident.get("condition_name") or ""
    state = (incident.get("state") or "open").lower()
    severity = "critical" if state == "open" else "info"

    title_parts = [policy_name]
    if condition_name:
        title_parts.append(f"— {condition_name}")
    title = " ".join(title_parts)
    summary = incident.get("summary") or f"Monitoring incident state={state}."

    labels = {
        "policy_name": str(policy_name),
        "condition_name": str(condition_name),
        "state": str(state),
    }
    if incident.get("resource_type_display_name"):
        labels["resource_type"] = str(incident["resource_type_display_name"])
    if incident.get("scoping_project_id"):
        labels["project_id"] = str(incident["scoping_project_id"])

    links: dict[str, str] = {}
    if incident.get("url"):
        links["Monitoring incident"] = str(incident["url"])

    return CanonicalAlert(
        cloud="gcp",
        environment=attrs.get("environment", "unknown"),
        project=incident.get("scoping_project_id") or attrs.get("project_id"),
        kind="service",
        severity=severity,
        title=title,
        summary=summary,
        labels=labels,
        links=links,
        source_payload=decoded,
    )


def _from_canonical(
    decoded: dict[str, Any], attrs: dict[str, Any]
) -> CanonicalAlert:
    return CanonicalAlert(
        cloud="gcp",
        environment=decoded.get("environment", attrs.get("environment", "unknown")),
        project=decoded.get("project_id") or decoded.get("project") or attrs.get("project_id"),
        account=decoded.get("billing_account_id") or attrs.get("billingAccountId"),
        service=decoded.get("service_name") or decoded.get("service") or attrs.get("service"),
        kind=decoded.get("kind", attrs.get("kind", "generic")),
        severity=decoded.get("severity", attrs.get("severity", "medium")),
        title=decoded.get("title", "GCP Alert"),
        summary=decoded.get("summary", "Alert received from GCP Pub/Sub."),
        runbook_url=decoded.get("runbook_url"),
        owner=decoded.get("owner"),
        route_key=decoded.get("route_key"),
        labels=decoded.get("labels", {}) or {},
        annotations=decoded.get("annotations", {}) or {},
        metrics=decoded.get("metrics", {}) or {},
        links=decoded.get("links", {}) or {},
        source_payload=decoded,
    )


def from_gcp_pubsub(payload: dict[str, Any]) -> CanonicalAlert:
    # Accept either the envelope or the inner message dict directly.
    message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    data = message.get("data")
    attrs = message.get("attributes") or {}
    decoded = _decode_data(data) if isinstance(data, str) else {}

    if _looks_like_native_budget(decoded):
        return _from_native_budget(decoded, attrs)
    if _looks_like_monitoring_incident(decoded):
        return _from_monitoring_incident(decoded, attrs)
    return _from_canonical(decoded, attrs)
