"""Render :class:`CanonicalAlert` into Slack Block Kit and simple email bodies.

Kept intentionally plain so audits can diff the output without fighting
template-engine syntax. If you need richer formatting per-feature, add a
``render_slack`` override on the feature class.
"""

from __future__ import annotations

from .models import CanonicalAlert, EmailMessage, SlackMessage

_SEVERITY_EMOJI = {
    "critical": ":rotating_light:",
    "high": ":red_circle:",
    "medium": ":large_orange_diamond:",
    "low": ":large_yellow_circle:",
    "info": ":information_source:",
}


def render_slack(alert: CanonicalAlert, channel: str | None) -> SlackMessage:
    sev = alert.severity.lower()
    emoji = _SEVERITY_EMOJI.get(sev, ":bell:")
    header = f"{emoji} [{alert.severity.upper()}] {alert.title}"
    summary = alert.summary

    fields = [
        {"type": "mrkdwn", "text": f"*Cloud:* `{alert.cloud}`"},
        {"type": "mrkdwn", "text": f"*Environment:* `{alert.environment}`"},
        {"type": "mrkdwn", "text": f"*Project:* `{alert.project or 'n/a'}`"},
        {"type": "mrkdwn", "text": f"*Service:* `{alert.service or 'n/a'}`"},
        {"type": "mrkdwn", "text": f"*Type:* `{alert.kind}`"},
        {"type": "mrkdwn", "text": f"*Owner:* {alert.owner or 'n/a'}"},
    ]

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary[:2800]}},
        {"type": "section", "fields": fields},
    ]

    if alert.runbook_url:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f":books: *Runbook:* {alert.runbook_url}"}],
            }
        )
    if alert.links:
        link_text = "  •  ".join(f"<{url}|{name}>" for name, url in alert.links.items())
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": link_text}]})

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"event_id `{alert.event_id}`"}],
        }
    )

    return SlackMessage(text=header, blocks=blocks, channel=channel)


def render_email(alert: CanonicalAlert, recipients: list[str], from_address: str = "alerts@example.com") -> EmailMessage:
    subject = f"[{alert.severity.upper()}] {alert.title}"
    body_lines = [
        f"From: {from_address}",
        f"Summary: {alert.summary}",
        "",
        f"Cloud:        {alert.cloud}",
        f"Environment:  {alert.environment}",
        f"Project:      {alert.project or 'n/a'}",
        f"Service:      {alert.service or 'n/a'}",
        f"Type:         {alert.kind}",
        f"Severity:     {alert.severity}",
        f"Owner:        {alert.owner or 'n/a'}",
        f"Runbook:      {alert.runbook_url or 'n/a'}",
        f"Event ID:     {alert.event_id}",
    ]
    if alert.labels:
        body_lines.append("")
        body_lines.append("Labels:")
        for key, value in sorted(alert.labels.items()):
            body_lines.append(f"  {key}: {value}")
    return EmailMessage(subject=subject, body_text="\n".join(body_lines), recipients=recipients)
