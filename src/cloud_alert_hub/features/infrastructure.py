"""Infrastructure spike alerts — CPU / memory / disk / network pressure."""

from __future__ import annotations

from ..models import CanonicalAlert
from .base import Feature, FeatureMatch


class InfrastructureSpikeFeature(Feature):
    name = "infrastructure_spike"

    def claims(self, alert: CanonicalAlert) -> bool:
        return alert.kind == "infrastructure"

    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        metric = alert.labels.get("metric", "unknown")
        threshold = alert.labels.get("threshold", "unknown")
        dedupe_key = f"{alert.cloud}:{alert.project or 'unknown'}:{metric}:{threshold}"
        return FeatureMatch(
            feature_name=self.name,
            route_key=self.route_key,
            severity=alert.severity or "medium",
            labels={"category": "operations"},
            dedupe_key=dedupe_key,
            dedupe_window_seconds=self.dedupe_window_seconds,
            extra_trace={"metric": metric, "threshold": threshold},
        )
