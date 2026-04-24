"""Azure Event Grid adapter.

Event Grid batches events; the first event in the list is used (callers who
want fan-out can iterate and call :func:`from_azure_eventgrid` per event).
"""

from __future__ import annotations

from typing import Any

from ..models import CanonicalAlert


def from_azure_eventgrid(payload: list[dict[str, Any]] | dict[str, Any]) -> CanonicalAlert:
    event = payload[0] if isinstance(payload, list) and payload else payload if isinstance(payload, dict) else {}
    data = event.get("data", {}) or {}
    return CanonicalAlert(
        cloud="azure",
        environment=data.get("environment", "unknown"),
        project=data.get("subscriptionName") or data.get("resourceGroup"),
        account=data.get("subscriptionId"),
        service=data.get("service_name") or data.get("service"),
        kind=data.get("kind", "generic"),
        severity=data.get("severity", "medium"),
        title=data.get("title") or event.get("subject") or "Azure Alert",
        summary=data.get("summary", "Alert received from Azure Event Grid."),
        runbook_url=data.get("runbook_url"),
        owner=data.get("owner"),
        route_key=data.get("route_key"),
        labels=data.get("labels", {}) or {},
        annotations=data.get("annotations", {}) or {},
        metrics=data.get("metrics", {}) or {},
        links=data.get("links", {}) or {},
        source_payload=data,
    )
