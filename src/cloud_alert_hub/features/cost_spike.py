"""Cost / usage spike alerts.

A **cost spike** is qualitatively different from a budget threshold:

* Budget thresholds are *level-triggered* — they fire when cumulative spend
  for the billing period crosses a known step (50%, 90%, 100%, ...). They
  tell you "you have crossed a line you drew."
* Spikes are *delta-triggered* — they fire when a service's spend or usage
  in a given window jumps significantly compared to its recent baseline.
  They tell you "something started behaving abnormally on day X."

Both are useful, and they're independent. A budget alert may take days to
fire (the bill has to accumulate), but a spike fires *the moment* an
abusive client starts hammering an API or a runaway autoscaler scales up.

This feature is **service-agnostic**: the service name comes from the
payload (``alert.service``) so you don't have to enumerate every GCP / AWS
service up-front. If a previously-quiet service starts costing money, this
feature alerts on it without any code change. Optional ``service_allowlist``
/ ``service_denylist`` knobs let operators carve out scope.

Sources of spike events (none of them require a new managed service —
they all use built-in cloud primitives):

* **GCP** — a Cloud Monitoring alert policy on built-in metrics like
  ``serviceruntime.googleapis.com/api/request_count`` (per service) with a
  Pub/Sub notification channel; or a BigQuery scheduled query against the
  Cloud Billing export that publishes anomalies to Pub/Sub.
* **AWS** — a CloudWatch alarm on ``AWS/Usage`` metrics or AWS Cost
  Anomaly Detection → SNS.
* **Azure** — Azure Monitor alert on cost metrics → Action Group with a
  webhook to the function.

The canonical payload looks like::

    {
        "kind": "cost_spike",
        "service": "Vertex AI",
        "summary": "Vertex AI spend jumped from $48/day avg to $5,021 today",
        "metrics": {
            "previous_amount":  48.13,    # baseline (e.g. 7-day rolling avg)
            "current_amount":  5021.44,    # observed window
            "delta_percent":  10333.0,
        },
        "labels": {
            "spike_window":  "1d",
            "spike_period":  "2026-04-21",
        }
    }

The dedupe key includes the service and the spike period, so a single
spike fires once per (cloud × project × service × period). A second spike
for the same service the next day fires again because ``spike_period``
rotates.
"""

from __future__ import annotations

from typing import Iterable

from ..models import CanonicalAlert
from .base import Feature, FeatureMatch


class CostSpikeFeature(Feature):
    """Alert on sudden cost / usage spikes per service.

    Settings (all optional)::

        features:
          cost_spike:
            enabled: true
            route: finops
            dedupe_window_seconds: 86400          # 1 day
            severity_thresholds_percent:
              medium:  100        # +100% over baseline
              high:    300
              critical: 1000
            service_allowlist: []                 # [] = all services
            service_denylist:
              - "BigQuery Reservation API"
    """

    name = "cost_spike"

    def claims(self, alert: CanonicalAlert) -> bool:
        return alert.kind == "cost_spike"

    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        service = (alert.service or alert.labels.get("service") or "unknown").strip()
        period = alert.labels.get("spike_period") or alert.labels.get("period_start") or "no_period"
        delta = self._delta_percent(alert)
        severity = self._severity_for_delta(delta)

        # Filter by allow/deny list. Note: we do NOT just drop the alert —
        # we instead emit a feature match with a bogus dedupe key + low
        # severity, then the policy can suppress via routing. But for now
        # we keep it simple: if denied, we still claim but mark severity
        # "info" so it's routed but not noisy. Operators who want hard
        # filtering should use route-level filtering downstream.
        denied = self._is_filtered_out(service)
        if denied:
            severity = "info"

        dedupe_key = (
            f"{alert.cloud}:{alert.project or 'unknown'}:{service}:{period}"
        )
        return FeatureMatch(
            feature_name=self.name,
            route_key=self.route_key,
            severity=severity,
            labels={
                "category": "cost",
                "service": service,
                "spike_period": str(period),
            },
            dedupe_key=dedupe_key,
            dedupe_window_seconds=self.dedupe_window_seconds,
            extra_trace={
                "service": service,
                "spike_period": period,
                "delta_percent": delta,
                "filtered_out": denied,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _delta_percent(self, alert: CanonicalAlert) -> float | None:
        """Pick the most reliable delta-percent signal we can find.

        Preference order:
            1. ``metrics.delta_percent`` — set by the producer.
            2. computed from ``metrics.previous_amount`` and
               ``metrics.current_amount`` if both are present.
            3. ``labels.delta_percent`` (string fallback).
        """
        metrics = alert.metrics or {}
        if "delta_percent" in metrics:
            try:
                return float(metrics["delta_percent"])
            except (TypeError, ValueError):
                pass
        prev = metrics.get("previous_amount")
        cur = metrics.get("current_amount")
        if isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and prev:
            try:
                return (float(cur) - float(prev)) / float(prev) * 100.0
            except ZeroDivisionError:
                return None
        raw = (alert.labels or {}).get("delta_percent")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        return None

    def _severity_for_delta(self, delta: float | None) -> str:
        ladder = self._settings.get("severity_thresholds_percent") or {}
        try:
            critical = float(ladder.get("critical", 1000))
            high = float(ladder.get("high", 300))
            medium = float(ladder.get("medium", 100))
        except (TypeError, ValueError):
            critical, high, medium = 1000.0, 300.0, 100.0

        if delta is None:
            # We have no quantitative signal — default to high so it gets
            # eyes, but the trace will note `delta_percent: None`.
            return "high"
        if delta >= critical:
            return "critical"
        if delta >= high:
            return "high"
        if delta >= medium:
            return "medium"
        return "low"

    def _is_filtered_out(self, service: str) -> bool:
        allow = self._listify(self._settings.get("service_allowlist"))
        deny = self._listify(self._settings.get("service_denylist"))
        # An empty allowlist means "all services allowed".
        if allow and service not in allow:
            return True
        if deny and service in deny:
            return True
        return False

    @staticmethod
    def _listify(raw: Iterable[str] | None) -> list[str]:
        if not raw:
            return []
        return [str(item).strip() for item in raw if str(item).strip()]
