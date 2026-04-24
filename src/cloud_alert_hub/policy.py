"""Policy engine — routes an incoming alert through enabled features.

Flow:
    1. Apply safe payload overrides (subset of keys allowed by config).
    2. Check global kill-switch (``app.alerting_enabled``).
    3. Ask each enabled feature ``claims(alert)``; the first match wins.
    4. Build the DeliveryTarget from the matched route.
    5. Consult the dedupe state store — suppress if within window.
"""

from __future__ import annotations

from typing import Any

from .config import Config
from .features import Feature, load_enabled_features
from .models import CanonicalAlert, DeliveryTarget, PolicyDecision
from .state import BaseState


def _apply_payload_overrides(alert: CanonicalAlert, config: Config) -> bool:
    """Mutate ``alert`` with any allow-listed overrides from the source payload.

    Returns ``True`` if any override was applied.
    """
    if not config.payload_overrides_enabled:
        return False
    payload = alert.source_payload or {}
    overrides = payload.get("overrides", {})
    if not isinstance(overrides, dict) or not overrides:
        return False
    allowed = config.payload_override_keys
    applied = False
    for key, value in overrides.items():
        if key in allowed and hasattr(alert, key):
            setattr(alert, key, value)
            applied = True
    return applied


def _build_delivery_target(config: Config, route_key: str) -> DeliveryTarget:
    route = config.route(route_key)
    slack_channel = route.get("slack_channel") or config.slack_default_channel
    return DeliveryTarget(
        slack_enabled=config.slack_enabled and bool(slack_channel),
        slack_channel=slack_channel,
        email_enabled=config.email_enabled and bool(route.get("email_recipients")),
        email_recipients=list(route.get("email_recipients", []) or []),
    )


def evaluate_policy(alert: CanonicalAlert, config: Config, state: BaseState) -> PolicyDecision:
    trace: dict[str, Any] = {
        "incoming_kind": alert.kind,
        "incoming_route_key": alert.route_key,
        "override_applied": _apply_payload_overrides(alert, config),
        "enabled_features": config.enabled_features(),
    }

    if not config.alerting_enabled:
        return PolicyDecision(
            alert=alert,
            route_key=config.default_route,
            target=DeliveryTarget(),
            should_deliver=False,
            suppressed_reason="global_alerting_disabled",
            trace=trace,
        )

    features: list[Feature] = load_enabled_features(config)
    matched = None
    for feature in features:
        if feature.claims(alert):
            matched = feature.match(alert)
            break

    if matched is None:
        route_key = alert.route_key or config.default_route
        target = _build_delivery_target(config, route_key)
        return PolicyDecision(
            alert=alert,
            route_key=route_key,
            target=target,
            should_deliver=False,
            suppressed_reason="no_feature_claimed",
            trace={**trace, "route_key": route_key},
        )

    if matched.severity:
        alert.severity = matched.severity  # type: ignore[assignment]
    if matched.labels:
        alert.labels.update(matched.labels)

    route_key = alert.route_key or matched.route_key
    target = _build_delivery_target(config, route_key)

    if matched.dedupe_key and state.should_suppress(matched.dedupe_key, matched.dedupe_window_seconds):
        return PolicyDecision(
            alert=alert,
            route_key=route_key,
            target=target,
            should_deliver=False,
            suppressed_reason="dedupe_window",
            delivery_tags={"dedupe_key": matched.dedupe_key},
            trace={
                **trace,
                "matched_feature": matched.feature_name,
                "route_key": route_key,
                "dedupe_key": matched.dedupe_key,
                "dedupe_window_seconds": matched.dedupe_window_seconds,
                **matched.extra_trace,
            },
        )

    return PolicyDecision(
        alert=alert,
        route_key=route_key,
        target=target,
        should_deliver=True,
        delivery_tags={"dedupe_key": matched.dedupe_key or ""},
        trace={
            **trace,
            "matched_feature": matched.feature_name,
            "route_key": route_key,
            "dedupe_key": matched.dedupe_key or "",
            "dedupe_window_seconds": matched.dedupe_window_seconds,
            "target": {
                "slack_enabled": target.slack_enabled,
                "slack_channel": target.slack_channel,
                "email_enabled": target.email_enabled,
                "email_recipient_count": len(target.email_recipients),
            },
            **matched.extra_trace,
        },
    )
