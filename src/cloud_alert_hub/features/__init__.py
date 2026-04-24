"""Feature registry.

Each feature module exports one concrete subclass of :class:`Feature`. The
registry below is the single place that knows about them — to add a feature:

    1. Create ``my_feature.py`` with a ``class MyFeature(Feature): ...``.
    2. Import and append it to ``FEATURE_CLASSES`` below.
    3. Add the matching section to ``bundled_defaults.yaml`` (with
       ``enabled: false``) so users see it but opt in explicitly.
"""

from __future__ import annotations

from typing import Iterable

from ..config import Config
from .base import Feature, FeatureMatch
from .budget import BudgetAlertsFeature
from .infrastructure import InfrastructureSpikeFeature
from .security_audit import SecurityAuditFeature
from .service_slo import ServiceSloFeature

FEATURE_CLASSES: tuple[type[Feature], ...] = (
    BudgetAlertsFeature,
    ServiceSloFeature,
    SecurityAuditFeature,
    InfrastructureSpikeFeature,
)


def load_enabled_features(config: Config) -> list[Feature]:
    """Instantiate only the features enabled in ``config.features``."""
    enabled: list[Feature] = []
    for cls in FEATURE_CLASSES:
        settings = config.feature(cls.name)
        if settings.get("enabled"):
            enabled.append(cls(settings=settings))
    return enabled


def feature_names() -> Iterable[str]:
    return (cls.name for cls in FEATURE_CLASSES)


__all__ = [
    "Feature",
    "FeatureMatch",
    "FEATURE_CLASSES",
    "load_enabled_features",
    "feature_names",
]
