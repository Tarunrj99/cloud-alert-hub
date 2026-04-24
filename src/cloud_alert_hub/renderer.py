"""Render :class:`CanonicalAlert` into Slack Block Kit messages and email bodies.

The Slack layout is **config-driven** — operators can toggle each visual
section on/off (``notifications.slack.display.*``) without editing code. This
is intentional: different audiences want different density.

Layout (top → bottom):
    1. Header      — emoji + severity + concise title
    2. Summary     — 1-2 line human summary
    3. Progress    — unicode progress bar for budget alerts (spend vs budget)
    4. Fields      — structured key/value pairs (cloud, env, project, …)
    5. Metrics     — numeric metrics from the payload (cost, latency, …)
    6. Labels      — free-form label dict (if any)
    7. Links       — runbook + any extra links
    8. Footer      — event_id + occurred_at + route

Any of these can be suppressed via config. Defaults live in
``bundled_defaults.yaml`` under ``notifications.slack.display``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .models import CanonicalAlert, EmailMessage, SlackMessage

# -----------------------------------------------------------------------------
# Severity visuals
# -----------------------------------------------------------------------------

_SEVERITY_EMOJI = {
    "critical": ":rotating_light:",
    "high": ":red_circle:",
    "medium": ":large_orange_diamond:",
    "low": ":large_yellow_circle:",
    "info": ":information_source:",
}

_SEVERITY_PILL = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
}

_KIND_EMOJI = {
    "budget": ":moneybag:",
    "service": ":gear:",
    "security": ":shield:",
    "infrastructure": ":building_construction:",
    "generic": ":bell:",
}

# Default toggles — mirrored in bundled_defaults.yaml. Keeping them here means
# the renderer still works if a caller passes a bare dict without defaults.
_DEFAULT_DISPLAY = {
    "show_header": True,
    "show_summary": True,
    "show_progress_bar": True,
    "show_fields": True,
    "show_metrics": True,
    "show_labels": False,  # noisy by default — opt in
    "show_links": True,
    "show_footer": True,
    "show_cloud": True,
    "show_environment": True,
    "show_project": True,
    "show_service": True,
    "show_kind": True,
    "show_owner": True,
    "show_account": False,
    "show_event_id": True,
    "show_occurred_at": True,
    "show_route": True,
    "progress_bar_width": 20,
    "label_allow_list": [],   # empty = show all when show_labels is True
    "label_deny_list": [],
    "metric_allow_list": [],
}


def _resolve_display(display_cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    resolved = dict(_DEFAULT_DISPLAY)
    if display_cfg:
        for k, v in display_cfg.items():
            resolved[k] = v
    return resolved


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _format_timestamp(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _currency_symbol(code: str | None) -> str:
    return {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get((code or "").upper(), "")


def _format_currency_amount(amount: float | int | None, currency: str | None) -> str:
    if amount is None:
        return "n/a"
    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    sym = _currency_symbol(currency)
    return f"{sym}{amount_f:,.2f}" + (f" {currency}" if not sym and currency else "")


def _progress_bar(fraction: float, width: int = 20) -> str:
    """Unicode progress bar. Caps visible fill at ``width`` but still shows
    overshoot as a numeric suffix (e.g. ``████████████████████  210%``).
    """
    if fraction < 0:
        fraction = 0
    visible = min(1.0, fraction)
    filled = int(round(visible * width))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return bar


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# -----------------------------------------------------------------------------
# Block builders — each returns either a block dict or None to suppress it.
# -----------------------------------------------------------------------------


def _header_block(alert: CanonicalAlert) -> dict:
    sev = alert.severity.lower()
    sev_pill = _SEVERITY_PILL.get(sev, alert.severity.upper())
    # Slack `header` blocks only accept plain_text, no emoji shortcodes, so
    # visual emojis are rendered by the severity banner section below.
    text = _truncate(f"[{sev_pill}] {alert.title}", 150)
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _severity_banner(alert: CanonicalAlert) -> dict:
    """A one-line banner right under the header to display emojis (which the
    header block can't)."""
    sev = alert.severity.lower()
    sev_emoji = _SEVERITY_EMOJI.get(sev, ":bell:")
    kind_emoji = _KIND_EMOJI.get(alert.kind, ":bell:")
    pieces = [f"{sev_emoji} *{_SEVERITY_PILL.get(sev, alert.severity.upper())}*"]
    pieces.append(f"{kind_emoji} `{alert.kind}`")
    if alert.environment and alert.environment != "unknown":
        pieces.append(f":earth_asia: `{alert.environment}`")
    return {"type": "section", "text": {"type": "mrkdwn", "text": "   ".join(pieces)}}


def _summary_block(alert: CanonicalAlert) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": _truncate(alert.summary, 2800)}}


def _progress_block(alert: CanonicalAlert, width: int) -> dict | None:
    if alert.kind != "budget":
        return None
    metrics = alert.metrics or {}
    cost = metrics.get("cost_amount")
    budget = metrics.get("budget_amount")
    threshold_fraction = metrics.get("threshold_fraction")
    try:
        thr_percent = int(alert.labels.get("threshold_percent", 0))
    except (TypeError, ValueError):
        thr_percent = 0
    if threshold_fraction is None and budget and cost:
        threshold_fraction = cost / budget
    if threshold_fraction is None and thr_percent:
        threshold_fraction = thr_percent / 100
    if threshold_fraction is None:
        return None

    currency = alert.annotations.get("currencyCode") or alert.labels.get("currency") or "USD"
    cost_fmt = _format_currency_amount(cost, currency)
    budget_fmt = _format_currency_amount(budget, currency)

    bar = _progress_bar(threshold_fraction, width=width)
    pct = threshold_fraction * 100
    heading = f"*Spend progress:* `{bar}` *{pct:.0f}%*"
    detail = f"Spent {cost_fmt}  of  {budget_fmt}"
    return {"type": "section", "text": {"type": "mrkdwn", "text": f"{heading}\n{detail}"}}


def _fields_block(alert: CanonicalAlert, display: dict[str, Any]) -> dict | None:
    items: list[tuple[str, str]] = []
    if display["show_cloud"] and alert.cloud:
        items.append(("Cloud", f"`{alert.cloud}`"))
    if display["show_environment"] and alert.environment:
        items.append(("Environment", f"`{alert.environment}`"))
    if display["show_project"] and alert.project:
        items.append(("Project", f"`{alert.project}`"))
    if display["show_service"] and alert.service:
        items.append(("Service", f"`{alert.service}`"))
    if display["show_account"] and alert.account:
        items.append(("Account", f"`{alert.account}`"))
    if display["show_kind"] and alert.kind:
        items.append(("Type", f"`{alert.kind}`"))
    if display["show_owner"] and alert.owner:
        items.append(("Owner", alert.owner))
    if not items:
        return None
    return {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*{key}:*\n{value}"} for key, value in items[:10]
        ],
    }


def _metrics_block(alert: CanonicalAlert, display: dict[str, Any]) -> dict | None:
    metrics = alert.metrics or {}
    if not metrics:
        return None
    allow = set(display.get("metric_allow_list") or [])
    display_items: list[str] = []
    currency = alert.annotations.get("currencyCode") or alert.labels.get("currency") or "USD"
    for key, value in metrics.items():
        if allow and key not in allow:
            continue
        if key in {"cost_amount", "budget_amount"}:
            formatted = _format_currency_amount(value, currency)
        elif key == "threshold_fraction":
            continue
        elif isinstance(value, float):
            formatted = f"{value:,.2f}"
        else:
            formatted = str(value)
        display_items.append(f"• `{key}`: {formatted}")
    if not display_items:
        return None
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Metrics*\n" + "\n".join(display_items)},
    }


def _labels_block(alert: CanonicalAlert, display: dict[str, Any]) -> dict | None:
    labels = alert.labels or {}
    if not labels:
        return None
    allow = set(display.get("label_allow_list") or [])
    deny = set(display.get("label_deny_list") or [])
    items: list[str] = []
    for key, value in sorted(labels.items()):
        if key in deny:
            continue
        if allow and key not in allow:
            continue
        items.append(f"`{key}`=`{value}`")
    if not items:
        return None
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Labels*  " + "  ".join(items)},
    }


def _links_block(alert: CanonicalAlert) -> dict | None:
    parts: list[str] = []
    if alert.runbook_url:
        parts.append(f":books: <{alert.runbook_url}|Runbook>")
    for name, url in (alert.links or {}).items():
        parts.append(f":link: <{url}|{name}>")
    if not parts:
        return None
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": "   ".join(parts)}]}


def _footer_block(alert: CanonicalAlert, display: dict[str, Any]) -> dict | None:
    parts: list[str] = []
    if display["show_event_id"]:
        parts.append(f"`event_id` {alert.event_id}")
    if display["show_occurred_at"]:
        ts = _format_timestamp(alert.occurred_at)
        if ts:
            parts.append(f":clock3: {ts}")
    if display["show_route"] and alert.route_key:
        parts.append(f":compass: route `{alert.route_key}`")
    if not parts:
        return None
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": "   •   ".join(parts)}]}


# -----------------------------------------------------------------------------
# Public renderers
# -----------------------------------------------------------------------------


def render_slack(
    alert: CanonicalAlert,
    channel: str | None,
    display: Mapping[str, Any] | None = None,
) -> SlackMessage:
    cfg = _resolve_display(display)
    sev = alert.severity.lower()
    emoji = _SEVERITY_EMOJI.get(sev, ":bell:")
    fallback_text = f"{emoji} [{_SEVERITY_PILL.get(sev, alert.severity.upper())}] {alert.title}"

    blocks: list[dict] = []
    if cfg["show_header"]:
        blocks.append(_header_block(alert))
        blocks.append(_severity_banner(alert))
    if cfg["show_summary"] and alert.summary:
        blocks.append(_summary_block(alert))
    if cfg["show_progress_bar"]:
        pb = _progress_block(alert, width=int(cfg["progress_bar_width"]))
        if pb:
            blocks.append(pb)
    if cfg["show_fields"]:
        fb = _fields_block(alert, cfg)
        if fb:
            blocks.append({"type": "divider"})
            blocks.append(fb)
    if cfg["show_metrics"]:
        mb = _metrics_block(alert, cfg)
        if mb:
            blocks.append(mb)
    if cfg["show_labels"]:
        lb = _labels_block(alert, cfg)
        if lb:
            blocks.append(lb)
    if cfg["show_links"]:
        lk = _links_block(alert)
        if lk:
            blocks.append(lk)
    if cfg["show_footer"]:
        fo = _footer_block(alert, cfg)
        if fo:
            blocks.append(fo)

    return SlackMessage(text=fallback_text, blocks=blocks, channel=channel)


def render_email(
    alert: CanonicalAlert, recipients: list[str], from_address: str = "alerts@example.com"
) -> EmailMessage:
    subject = f"[{alert.severity.upper()}] {alert.title}"
    body_lines = [
        f"Summary     : {alert.summary}",
        "",
        f"Cloud       : {alert.cloud}",
        f"Environment : {alert.environment}",
        f"Project     : {alert.project or 'n/a'}",
        f"Service     : {alert.service or 'n/a'}",
        f"Type        : {alert.kind}",
        f"Severity    : {alert.severity}",
        f"Owner       : {alert.owner or 'n/a'}",
        f"Occurred    : {_format_timestamp(alert.occurred_at) or 'n/a'}",
        f"Event ID    : {alert.event_id}",
    ]
    if alert.metrics:
        body_lines.append("")
        body_lines.append("Metrics:")
        for key, value in sorted(alert.metrics.items()):
            body_lines.append(f"  {key}: {value}")
    if alert.labels:
        body_lines.append("")
        body_lines.append("Labels:")
        for key, value in sorted(alert.labels.items()):
            body_lines.append(f"  {key}: {value}")
    if alert.runbook_url:
        body_lines.append("")
        body_lines.append(f"Runbook: {alert.runbook_url}")
    if alert.links:
        body_lines.append("")
        body_lines.append("Links:")
        for name, url in alert.links.items():
            body_lines.append(f"  {name}: {url}")
    body_lines.append("")
    body_lines.append(f"(sent from {from_address})")
    return EmailMessage(subject=subject, body_text="\n".join(body_lines), recipients=recipients)
