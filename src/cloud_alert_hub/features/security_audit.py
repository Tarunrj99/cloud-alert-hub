"""Security audit alerts — IAM / config / policy changes that auditors care about."""

from __future__ import annotations

from ..models import CanonicalAlert
from .base import Feature, FeatureMatch


class SecurityAuditFeature(Feature):
    name = "security_audit"

    def claims(self, alert: CanonicalAlert) -> bool:
        return alert.kind == "security"

    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        resource = alert.labels.get("resource", "unknown")
        action = alert.labels.get("action", "unknown")
        principal = alert.labels.get("principal", "unknown")
        dedupe_key = f"{alert.cloud}:{alert.project or 'unknown'}:{resource}:{action}:{principal}"
        return FeatureMatch(
            feature_name=self.name,
            route_key=self.route_key,
            severity=alert.severity or "critical",
            labels={"category": "governance"},
            dedupe_key=dedupe_key,
            dedupe_window_seconds=self.dedupe_window_seconds,
            extra_trace={"resource": resource, "action": action, "principal": principal},
        )
