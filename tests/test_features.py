"""Unit tests for the individual feature classes."""

from __future__ import annotations

from cloud_alert_hub.features import (
    BudgetAlertsFeature,
    CostSpikeFeature,
    InfrastructureSpikeFeature,
    SecurityAuditFeature,
    ServiceSloFeature,
    load_enabled_features,
)
from cloud_alert_hub.config import load_config
from cloud_alert_hub.models import CanonicalAlert


def _alert(**kwargs) -> CanonicalAlert:
    defaults = {"title": "t", "summary": "s", "cloud": "gcp"}
    defaults.update(kwargs)
    return CanonicalAlert(**defaults)


def test_budget_feature_severity_ladder() -> None:
    feat = BudgetAlertsFeature({"enabled": True, "route": "finops", "dedupe_window_seconds": 60})
    assert feat.claims(_alert(kind="budget"))
    low = feat.match(_alert(kind="budget", labels={"threshold_percent": "50", "budget_name": "b"}))
    med = feat.match(_alert(kind="budget", labels={"threshold_percent": "90", "budget_name": "b"}))
    high = feat.match(_alert(kind="budget", labels={"threshold_percent": "100", "budget_name": "b"}))
    crit = feat.match(_alert(kind="budget", labels={"threshold_percent": "200", "budget_name": "b"}))
    assert low.severity == "low"
    assert med.severity == "medium"
    assert high.severity == "high"
    assert crit.severity == "critical"
    assert "b" in low.dedupe_key


def test_budget_feature_dedupe_key_includes_billing_period() -> None:
    """Same threshold, different billing period → different dedup key.

    This is what prevents Slack noise: April's 300% alert is suppressed for
    all of April, but May 1's 50% alert fires fresh because the period
    component changed.
    """
    feat = BudgetAlertsFeature({"enabled": True, "route": "finops", "dedupe_window_seconds": 60})

    april = feat.match(
        _alert(
            kind="budget",
            project="p",
            labels={
                "threshold_percent": "300",
                "budget_name": "B",
                "cost_interval_start": "2026-04-01T00:00:00Z",
            },
        )
    )
    may = feat.match(
        _alert(
            kind="budget",
            project="p",
            labels={
                "threshold_percent": "300",
                "budget_name": "B",
                "cost_interval_start": "2026-05-01T00:00:00Z",
            },
        )
    )
    assert april.dedupe_key != may.dedupe_key
    assert "2026-04-01T00:00:00Z" in april.dedupe_key
    assert "2026-05-01T00:00:00Z" in may.dedupe_key
    assert april.extra_trace["billing_period"] == "2026-04-01T00:00:00Z"


def test_budget_feature_dedupe_key_falls_back_when_period_missing() -> None:
    """Older payloads (or non-GCP sources) may lack ``cost_interval_start``.

    The dedup key must still be deterministic — we use a sentinel marker so
    the key is well-formed and dedup works within a single process.
    """
    feat = BudgetAlertsFeature({"enabled": True, "route": "finops", "dedupe_window_seconds": 60})
    match = feat.match(
        _alert(kind="budget", project="p", labels={"threshold_percent": "100", "budget_name": "B"})
    )
    assert "no_period" in match.dedupe_key


def test_service_slo_feature_breach_detail() -> None:
    feat = ServiceSloFeature(
        {"enabled": True, "route": "sre", "dedupe_window_seconds": 60, "error_rate_percent_gte": 3, "latency_p95_ms_gte": 500}
    )
    match = feat.match(
        _alert(kind="service", service="api", labels={"incident_key": "i"}, metrics={"error_rate_percent": 5, "latency_p95_ms": 700})
    )
    assert "error_rate=" in match.extra_trace["breach_detail"]
    assert "p95=" in match.extra_trace["breach_detail"]


def test_security_and_infra_features_dedupe_keys() -> None:
    sec = SecurityAuditFeature({"enabled": True, "route": "security", "dedupe_window_seconds": 60})
    s_match = sec.match(_alert(kind="security", project="p", labels={"resource": "r", "action": "a", "principal": "u"}))
    assert s_match.dedupe_key == "gcp:p:r:a:u"

    infra = InfrastructureSpikeFeature({"enabled": True, "route": "sre", "dedupe_window_seconds": 60})
    i_match = infra.match(_alert(kind="infrastructure", project="p", labels={"metric": "cpu", "threshold": "80"}))
    assert i_match.dedupe_key == "gcp:p:cpu:80"


def test_load_enabled_features_respects_flags() -> None:
    cfg = load_config(
        {
            "features": {
                "budget_alerts": {"enabled": True},
                "service_slo": {"enabled": False},
                "security_audit": {"enabled": True},
                "infrastructure_spike": {"enabled": False},
                "cost_spike": {"enabled": False},
            }
        }
    )
    enabled = {f.name for f in load_enabled_features(cfg)}
    assert enabled == {"budget_alerts", "security_audit"}


# ---------------------------------------------------------------------------
# CostSpikeFeature
# ---------------------------------------------------------------------------


def _spike_alert(**overrides) -> CanonicalAlert:
    return _alert(
        kind="cost_spike",
        service=overrides.pop("service", "Vertex AI"),
        project=overrides.pop("project", "p"),
        labels=overrides.pop(
            "labels",
            {"spike_period": "2026-04-21"},
        ),
        metrics=overrides.pop(
            "metrics",
            {"previous_amount": 50.0, "current_amount": 5000.0, "delta_percent": 9900.0},
        ),
        **overrides,
    )


def test_cost_spike_feature_claims_only_cost_spike_kind() -> None:
    feat = CostSpikeFeature({"enabled": True, "route": "finops"})
    assert feat.claims(_spike_alert())
    assert not feat.claims(_alert(kind="budget"))
    assert not feat.claims(_alert(kind="service"))


def test_cost_spike_feature_dedupe_key_is_cloud_project_service_period() -> None:
    feat = CostSpikeFeature({"enabled": True, "route": "finops"})
    match = feat.match(_spike_alert())
    assert match.dedupe_key == "gcp:p:Vertex AI:2026-04-21"


def test_cost_spike_feature_severity_ladder_uses_delta_percent() -> None:
    feat = CostSpikeFeature(
        {
            "enabled": True,
            "route": "finops",
            "severity_thresholds_percent": {"medium": 100, "high": 300, "critical": 1000},
        }
    )
    low = feat.match(_spike_alert(metrics={"delta_percent": 50}))
    medium = feat.match(_spike_alert(metrics={"delta_percent": 150}))
    high = feat.match(_spike_alert(metrics={"delta_percent": 500}))
    crit = feat.match(_spike_alert(metrics={"delta_percent": 5000}))
    assert (low.severity, medium.severity, high.severity, crit.severity) == (
        "low",
        "medium",
        "high",
        "critical",
    )


def test_cost_spike_feature_computes_delta_from_previous_and_current() -> None:
    """No ``delta_percent`` metric, but previous + current present → compute."""
    feat = CostSpikeFeature({"enabled": True, "route": "finops"})
    match = feat.match(
        _spike_alert(metrics={"previous_amount": 100.0, "current_amount": 500.0})
    )
    # +400% → high
    assert match.severity == "high"
    assert match.extra_trace["delta_percent"] == 400.0


def test_cost_spike_feature_unknown_delta_defaults_to_high() -> None:
    """No quantitative signal anywhere → default high (visible but not critical)."""
    feat = CostSpikeFeature({"enabled": True, "route": "finops"})
    match = feat.match(_spike_alert(metrics={}, labels={"spike_period": "2026-04-21"}))
    assert match.severity == "high"
    assert match.extra_trace["delta_percent"] is None


def test_cost_spike_feature_allowlist_filters_to_named_services() -> None:
    feat = CostSpikeFeature(
        {
            "enabled": True,
            "route": "finops",
            "service_allowlist": ["Vertex AI", "Generative Language API"],
        }
    )
    listed = feat.match(_spike_alert(service="Vertex AI"))
    other = feat.match(_spike_alert(service="Cloud Storage"))
    # Allowlisted services pass through with their delta-derived severity.
    assert listed.severity != "info"
    assert listed.extra_trace["filtered_out"] is False
    # Non-allowlisted services are downgraded to info.
    assert other.severity == "info"
    assert other.extra_trace["filtered_out"] is True


def test_cost_spike_feature_denylist_drops_specific_services() -> None:
    feat = CostSpikeFeature(
        {
            "enabled": True,
            "route": "finops",
            "service_denylist": ["BigQuery Reservation API"],
        }
    )
    blocked = feat.match(_spike_alert(service="BigQuery Reservation API"))
    other = feat.match(_spike_alert(service="Vertex AI"))
    assert blocked.severity == "info"
    assert blocked.extra_trace["filtered_out"] is True
    assert other.severity != "info"
