"""Base class + data types for pluggable alerting features.

A *feature* is a self-contained alerting scenario (budget overruns, service SLO
breaches, security audit events, infrastructure spikes, …). Each feature knows:

* its **name** (as used in ``config.features.<name>``)
* how to **claim** an incoming :class:`CanonicalAlert` — i.e. does this feature
  own this event?
* which **route** in ``config.routing.routes`` to use
* the **dedupe key template** and window
* optional **severity / label enrichment** applied before rendering

Features are just Python classes; to add one, subclass :class:`Feature` and
register it in ``cloud_alert_hub.features.registry``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models import CanonicalAlert


@dataclass
class FeatureMatch:
    """Result of a feature claiming an alert."""

    feature_name: str
    route_key: str
    severity: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    dedupe_key: str | None = None
    dedupe_window_seconds: int = 900
    extra_trace: dict[str, Any] = field(default_factory=dict)


class Feature(ABC):
    """Abstract base class for a toggleable alerting feature."""

    #: Feature name — must match the key under ``config.features``.
    name: str = ""

    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = settings or {}

    # ---- public helpers ----------------------------------------------------

    @property
    def settings(self) -> dict[str, Any]:
        return self._settings

    @property
    def route_key(self) -> str:
        return str(self._settings.get("route", "finops"))

    @property
    def dedupe_window_seconds(self) -> int:
        return int(self._settings.get("dedupe_window_seconds", 900))

    # ---- subclass contract -------------------------------------------------

    @abstractmethod
    def claims(self, alert: CanonicalAlert) -> bool:
        """Return ``True`` if this feature should handle the incoming alert."""

    @abstractmethod
    def match(self, alert: CanonicalAlert) -> FeatureMatch:
        """Return a :class:`FeatureMatch` describing routing + dedupe for the alert.

        Called only after :meth:`claims` returns ``True``.
        """
