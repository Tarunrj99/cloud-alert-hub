"""Slack webhook delivery.

Webhook URL is resolved via the env var named in ``notifications.slack.webhook_url_env``
so operators can rotate credentials without editing YAML.
"""

from __future__ import annotations

import os

import httpx

from ..models import SlackMessage


def send_slack(
    message: SlackMessage,
    webhook_env_var: str = "SLACK_WEBHOOK_URL",
    timeout_seconds: int = 8,
    dry_run: bool = False,
) -> dict:
    webhook_url = os.getenv(webhook_env_var, "").strip()
    if dry_run:
        return {"status": "dry_run", "channel": message.channel, "text": message.text}
    if not webhook_url:
        return {"status": "skipped", "reason": f"missing_env:{webhook_env_var}"}

    payload = {"text": message.text, "blocks": message.blocks}
    if message.channel:
        payload["channel"] = message.channel

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(webhook_url, json=payload)
    status = "sent" if response.status_code < 300 else "failed"
    return {"status": status, "status_code": response.status_code}
