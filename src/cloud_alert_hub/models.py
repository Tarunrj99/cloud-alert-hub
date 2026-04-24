from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]

# `kind` is intentionally a free-form string so users can define custom feature
# kinds without editing the library. Built-in features look for the canonical
# values "budget", "service", "security", "infrastructure", "generic".


class CanonicalAlert(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = None
    cloud: str = "unknown"
    environment: str = "unknown"
    project: str | None = None
    account: str | None = None
    service: str | None = None
    kind: str = "generic"
    severity: Severity = "medium"
    title: str
    summary: str
    runbook_url: str | None = None
    owner: str | None = None
    route_key: str | None = None
    dedupe_key: str | None = None
    mute_key: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)
    source_payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeliveryTarget(BaseModel):
    slack_enabled: bool = True
    slack_channel: str | None = None
    email_enabled: bool = False
    email_recipients: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    alert: CanonicalAlert
    route_key: str
    target: DeliveryTarget
    should_deliver: bool = True
    suppressed_reason: str | None = None
    delivery_tags: dict[str, str] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)


class SlackMessage(BaseModel):
    text: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    channel: str | None = None


class EmailMessage(BaseModel):
    subject: str
    body_text: str
    recipients: list[str]
