"""Unit tests for the individual feature classes."""

from __future__ import annotations

from cloud_alert_hub.features import (
    BudgetAlertsFeature,
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
            }
        }
    )
    enabled = {f.name for f in load_enabled_features(cfg)}
    assert enabled == {"budget_alerts", "security_audit"}
