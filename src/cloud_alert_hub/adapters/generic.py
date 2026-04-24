"""Generic adapter — pass-through for already-canonical payloads.

Use this when your producer speaks the canonical schema directly (useful for
testing and for internal services that don't go through a cloud broker).
"""

from __future__ import annotations

from typing import Any

from ..models import CanonicalAlert


def from_generic(payload: dict[str, Any]) -> CanonicalAlert:
    return CanonicalAlert(
        cloud=payload.get("cloud", "unknown"),
        environment=payload.get("environment", "unknown"),
        project=payload.get("project"),
        account=payload.get("account"),
        service=payload.get("service"),
        kind=payload.get("kind", "generic"),
        severity=payload.get("severity", "medium"),
        title=payload.get("title", "Generic Alert"),
        summary=payload.get("summary", "Alert received from generic source."),
        runbook_url=payload.get("runbook_url"),
        owner=payload.get("owner"),
        route_key=payload.get("route_key"),
        labels=payload.get("labels", {}) or {},
        annotations=payload.get("annotations", {}) or {},
        metrics=payload.get("metrics", {}) or {},
        links=payload.get("links", {}) or {},
        source_payload=payload,
    )
