"""GCP Pub/Sub adapter.

Handles both shapes you'll see in practice:

* **Background / 1st-gen Cloud Functions**: the platform hands you the decoded
  Pub/Sub message dict directly (``{"data": "<b64>", "attributes": {...}}``).
* **2nd-gen Cloud Functions / Cloud Run / Pub/Sub push HTTP**: the message is
  wrapped in an envelope (``{"message": {"data": "<b64>", ...}, "subscription": ...}``).

Either is accepted. Callers don't need to pre-normalize.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from ..models import CanonicalAlert


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


def from_gcp_pubsub(payload: dict[str, Any]) -> CanonicalAlert:
    # Accept either the envelope or the message dict directly.
    message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    data = message.get("data")
    attrs = message.get("attributes") or {}
    decoded = _decode_data(data) if isinstance(data, str) else {}

    return CanonicalAlert(
        cloud="gcp",
        environment=decoded.get("environment", attrs.get("environment", "unknown")),
        project=decoded.get("project_id") or decoded.get("project") or attrs.get("project_id"),
        account=decoded.get("billing_account_id") or attrs.get("billingAccountId"),
        service=decoded.get("service_name") or decoded.get("service") or attrs.get("service"),
        kind=decoded.get("kind", attrs.get("kind", "budget")),
        severity=decoded.get("severity", attrs.get("severity", "high")),
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
