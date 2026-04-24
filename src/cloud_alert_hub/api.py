"""Public façade for cloud_alert_hub.

End users import from here; nothing else in the package is guaranteed stable.
Each function is a thin, stateless wrapper around the internal pipeline so
Cloud Functions / Lambdas can call it in one line.
"""

from __future__ import annotations

from typing import Any

from .adapters import from_aws_sns, from_azure_eventgrid, from_gcp_pubsub, from_generic
from .config import Config, load_config
from .models import CanonicalAlert
from .processor import AlertProcessor
from .state import BaseState, create_state_backend
from .telemetry import MetricsTracker


def _build_pipeline(user_config: Any) -> tuple[Config, BaseState, MetricsTracker, AlertProcessor]:
    config = user_config if isinstance(user_config, Config) else load_config(user_config)
    state = create_state_backend(config)
    metrics = MetricsTracker()
    processor = AlertProcessor(config=config, state=state, metrics=metrics)
    return config, state, metrics, processor


def process_alert(alert: CanonicalAlert, config: Any = None) -> dict[str, Any]:
    """Process an already-canonical alert. Returns the processor result dict."""
    _, _, _, processor = _build_pipeline(config)
    return processor.process(alert)


def run(event: Any, source: str = "generic", config: Any = None) -> dict[str, Any]:
    """Universal entrypoint.

    Args:
        event:   the raw event delivered by the cloud runtime (Pub/Sub message,
                 SNS record, Event Grid batch, or canonical dict).
        source:  one of ``"gcp"``, ``"aws"``, ``"azure"``, or ``"generic"``.
        config:  a :class:`Config`, a dict, a path to a YAML file, a YAML
                 string, or ``None`` to use bundled defaults only.

    Returns a result dict suitable for logging or returning from a function.
    """
    source_key = (source or "generic").lower()
    if source_key in {"gcp", "gcp_pubsub", "google"}:
        alert = from_gcp_pubsub(event)
    elif source_key in {"aws", "aws_sns", "amazon"}:
        alert = from_aws_sns(event)
    elif source_key in {"azure", "azure_eventgrid", "microsoft"}:
        alert = from_azure_eventgrid(event)
    else:
        alert = from_generic(event)
    return process_alert(alert, config=config)


def handle_gcp_pubsub(event: Any, config: Any = None) -> dict[str, Any]:
    """Convenience for GCP Cloud Functions / Cloud Run Pub/Sub triggers."""
    return run(event, source="gcp", config=config)


def handle_aws_sns(event: Any, config: Any = None) -> dict[str, Any]:
    """Convenience for AWS Lambda SNS triggers."""
    return run(event, source="aws", config=config)


def handle_azure_eventgrid(event: Any, config: Any = None) -> dict[str, Any]:
    """Convenience for Azure Functions / App Service Event Grid triggers."""
    return run(event, source="azure", config=config)
