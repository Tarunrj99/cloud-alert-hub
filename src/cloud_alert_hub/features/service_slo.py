"""Service SLO alerts — latency / error-rate breach per service.

Expected inputs:
    * kind == "service"
    * metrics.error_rate_percent or metrics.latency_p95_ms populated by the
      upstream adapter (GCP Cloud Monitoring, CloudWatch, Azure Monitor, etc.).
"""

from __future__ import annotations

from ..models import CanonicalAlert
from .base import Feature, FeatureMatch


class ServiceSloFeature(Feature):
    name = "service_slo"

    def claims(self, alert: CanonicalAlert) -> bool:
        return alert.kind == "service"

    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        incident = alert.labels.get("incident_key", alert.labels.get("policy_id", "unknown"))
        dedupe_key = f"{alert.cloud}:{alert.service or 'unknown'}:{incident}"
        breach_detail = self._breach_detail(alert)
        return FeatureMatch(
            feature_name=self.name,
            route_key=self.route_key,
            severity=alert.severity or "high",
            labels={"category": "reliability", **({"breach": breach_detail} if breach_detail else {})},
            dedupe_key=dedupe_key,
            dedupe_window_seconds=self.dedupe_window_seconds,
            extra_trace={"breach_detail": breach_detail},
        )

    def _breach_detail(self, alert: CanonicalAlert) -> str:
        parts: list[str] = []
        error_rate = alert.metrics.get("error_rate_percent")
        latency = alert.metrics.get("latency_p95_ms")
        err_thr = self._settings.get("error_rate_percent_gte")
        lat_thr = self._settings.get("latency_p95_ms_gte")
        if error_rate is not None and err_thr is not None and error_rate >= err_thr:
            parts.append(f"error_rate={error_rate}%")
        if latency is not None and lat_thr is not None and latency >= lat_thr:
            parts.append(f"p95={latency}ms")
        return ",".join(parts)
