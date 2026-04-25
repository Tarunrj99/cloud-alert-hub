"""Budget alerts — triggered by cloud billing budget threshold breaches.

Typical sources:
    * GCP: Cloud Billing → Pub/Sub budget notifications
    * AWS: Budgets Service → SNS
    * Azure: Cost Management → Event Grid / Action Group

The canonical alert must carry ``kind="budget"`` and should include
``labels.threshold_percent`` and ``labels.budget_name`` for accurate dedupe.
"""

from __future__ import annotations

from ..models import CanonicalAlert
from .base import Feature, FeatureMatch


class BudgetAlertsFeature(Feature):
    name = "budget_alerts"

    def claims(self, alert: CanonicalAlert) -> bool:
        return alert.kind == "budget"

    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        threshold = alert.labels.get("threshold_percent", "unknown")
        budget = alert.labels.get("budget_name", alert.project or "unknown")
        # ``cost_interval_start`` is the ISO start of the current billing
        # period (set by the GCP Pub/Sub adapter). Including it scopes the
        # dedup key to "this threshold this period", so:
        #
        #   * Re-emissions of "300% reached" within April are suppressed
        #     for the entire month, no matter how long the operator's
        #     ``dedupe_window_seconds`` is set to.
        #   * On May 1, ``cost_interval_start`` flips to a new value, so
        #     "50% reached" fires a fresh alert even though the same key
        #     fired in April.
        period = alert.labels.get("cost_interval_start", "no_period")
        dedupe_key = (
            f"{alert.cloud}:{alert.project or 'unknown'}:{budget}:{period}:{threshold}"
        )
        return FeatureMatch(
            feature_name=self.name,
            route_key=self.route_key,
            severity=self._severity_for_threshold(threshold),
            labels={"category": "cost", "budget_name": budget},
            dedupe_key=dedupe_key,
            dedupe_window_seconds=self.dedupe_window_seconds,
            extra_trace={"threshold_percent": threshold, "billing_period": period},
        )

    @staticmethod
    def _severity_for_threshold(threshold_raw: str) -> str:
        try:
            pct = float(threshold_raw)
        except (TypeError, ValueError):
            return "high"
        if pct >= 200:
            return "critical"
        if pct >= 100:
            return "high"
        if pct >= 90:
            return "medium"
        return "low"
