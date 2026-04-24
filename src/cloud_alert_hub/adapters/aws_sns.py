"""AWS SNS adapter.

Works for:

* **Lambda SNS-triggered invocations**: ``event = {"Records": [{"Sns": {...}}]}``
* **Direct SNS HTTP notifications**: the SNS JSON object itself.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import CanonicalAlert


def _extract_sns(event: dict[str, Any]) -> dict[str, Any]:
    records = event.get("Records") or []
    if records and isinstance(records[0], dict):
        return records[0].get("Sns", {}) or {}
    # Direct SNS notification shape.
    if event.get("Type") == "Notification":
        return event
    return {}


def from_aws_sns(event: dict[str, Any]) -> CanonicalAlert:
    sns = _extract_sns(event)
    message_raw = sns.get("Message", "{}")
    try:
        message = json.loads(message_raw) if isinstance(message_raw, str) else (message_raw or {})
    except json.JSONDecodeError:
        message = {"summary": str(message_raw)}
    if not isinstance(message, dict):
        message = {"summary": str(message)}

    return CanonicalAlert(
        cloud="aws",
        environment=message.get("environment", "unknown"),
        project=message.get("account_alias") or message.get("account_id"),
        account=message.get("account_id"),
        service=message.get("service_name") or message.get("service"),
        kind=message.get("kind", "generic"),
        severity=message.get("severity", "medium"),
        title=message.get("title") or sns.get("Subject") or "AWS Alert",
        summary=message.get("summary", "Alert received from AWS SNS."),
        runbook_url=message.get("runbook_url"),
        owner=message.get("owner"),
        route_key=message.get("route_key"),
        labels=message.get("labels", {}) or {},
        annotations=message.get("annotations", {}) or {},
        metrics=message.get("metrics", {}) or {},
        links=message.get("links", {}) or {},
        source_payload=message,
    )
