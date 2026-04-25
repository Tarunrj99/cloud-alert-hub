"""Public façade for cloud_alert_hub.

End users import from here; nothing else in the package is guaranteed stable.
Each function is a thin, stateless wrapper around the internal pipeline so
Cloud Functions / Lambdas can call it in one line.
"""

from __future__ import annotations

import os
from typing import Any

from .adapters import from_aws_sns, from_azure_eventgrid, from_gcp_pubsub, from_generic
from .config import Config, load_config
from .models import CanonicalAlert
from .processor import AlertProcessor
from .state import BaseState, create_state_backend
from .telemetry import MetricsTracker

# Cloud-runtime env vars that name the project the function runs in. Used as
# the final fallback when neither the upstream payload nor app.project is set.
_RUNTIME_PROJECT_ENV_VARS = ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT", "AWS_ACCOUNT_ID")


def _build_pipeline(user_config: Any) -> tuple[Config, BaseState, MetricsTracker, AlertProcessor]:
    config = user_config if isinstance(user_config, Config) else load_config(user_config)
    state = create_state_backend(config)
    metrics = MetricsTracker()
    processor = AlertProcessor(config=config, state=state, metrics=metrics)
    return config, state, metrics, processor


def _enrich_from_config(alert: CanonicalAlert, config: Config) -> CanonicalAlert:
    """Backfill alert fields the upstream payload didn't provide.

    Native cloud-vendor payloads (e.g. GCP Cloud Billing budget messages,
    project-level CloudWatch SNS alarms) carry no notion of which
    environment / project they belong to — that's the operator's knowledge.
    If the adapter couldn't extract a value, fall back in this order:

    1. ``app.environment`` / ``app.cloud`` / ``app.project`` from config
    2. Cloud-runtime env vars (``GOOGLE_CLOUD_PROJECT``, ``GCP_PROJECT``)
       — set automatically by Cloud Functions / Cloud Run / Lambda

    This guarantees renderers always show useful context
    (``Environment: nonprod``, ``Project: my-project-id``) instead of
    defaulting to ``unknown`` / hiding the field.
    """
    if not alert.environment or alert.environment == "unknown":
        alert.environment = config.environment
    if not alert.cloud or alert.cloud == "unknown":
        alert.cloud = config.cloud
    if not alert.project:
        configured = str(config.get("app", "project", default="") or "").strip()
        if configured:
            alert.project = configured
        else:
            for env_name in _RUNTIME_PROJECT_ENV_VARS:
                runtime_value = (os.getenv(env_name) or "").strip()
                if runtime_value:
                    alert.project = runtime_value
                    break
    return alert


def process_alert(alert: CanonicalAlert, config: Any = None) -> dict[str, Any]:
    """Process an already-canonical alert. Returns the processor result dict."""
    cfg, _, _, processor = _build_pipeline(config)
    enriched = _enrich_from_config(alert, cfg)
    return processor.process(enriched)


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
