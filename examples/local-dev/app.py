"""Local FastAPI server — for development and manual testing only.

Not part of the production deployment path. Use the Cloud Function / Lambda
examples for that. This server is handy when you want to:

* Explore the library interactively (``/debug/config``, ``/debug/metrics``).
* ``curl`` a canonical alert to ``/ingest/generic`` while iterating on rules.
* Reproduce a production payload locally by replaying JSON from
  ``examples/payloads/``.

Run:

    pip install -e ".[server]"
    uvicorn examples.local-dev.app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from cloud_alert_hub import handle_aws_sns, handle_azure_eventgrid, handle_gcp_pubsub, load_config, run
from cloud_alert_hub.processor import AlertProcessor
from cloud_alert_hub.security import UnauthorizedError, verify_ingest_token
from cloud_alert_hub.state import create_state_backend
from cloud_alert_hub.telemetry import MetricsTracker

CONFIG_PATH = os.getenv("CLOUD_ALERT_HUB_CONFIG", str(Path(__file__).parent / "config.yaml"))
CONFIG = load_config(CONFIG_PATH)
STATE = create_state_backend(CONFIG)
METRICS = MetricsTracker()
PROCESSOR = AlertProcessor(config=CONFIG, state=STATE, metrics=METRICS)

app = FastAPI(title="cloud_alert_hub local-dev", version="0.1.0")


def _enforce_auth(authorization: str | None, x_alerting_token: str | None) -> None:
    try:
        verify_ingest_token(CONFIG, authorization, x_alerting_token)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "environment": CONFIG.environment,
        "cloud": CONFIG.cloud,
        "alerting_enabled": CONFIG.alerting_enabled,
        "debug_mode": CONFIG.debug_mode,
    }


@app.get("/debug/config")
def debug_config() -> dict[str, Any]:
    return {
        "environment": CONFIG.environment,
        "cloud": CONFIG.cloud,
        "alerting_enabled": CONFIG.alerting_enabled,
        "dry_run": CONFIG.dry_run,
        "debug_mode": CONFIG.debug_mode,
        "default_route": CONFIG.default_route,
        "enabled_features": CONFIG.enabled_features(),
        "ingress_auth_enabled": CONFIG.ingress_auth_enabled,
        "state_backend": CONFIG.state_backend,
    }


@app.get("/debug/metrics")
def debug_metrics() -> dict[str, int]:
    return METRICS.snapshot()


@app.post("/ingest/generic")
def ingest_generic(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_alerting_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _enforce_auth(authorization, x_alerting_token)
    return run(payload, source="generic", config=CONFIG)


@app.post("/ingest/gcp/pubsub")
def ingest_gcp_pubsub(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_alerting_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _enforce_auth(authorization, x_alerting_token)
    return handle_gcp_pubsub(payload, config=CONFIG)


@app.post("/ingest/aws/sns")
def ingest_aws_sns(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_alerting_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _enforce_auth(authorization, x_alerting_token)
    return handle_aws_sns(payload, config=CONFIG)


@app.post("/ingest/azure/eventgrid")
def ingest_azure_eventgrid(
    payload: Any,
    authorization: str | None = Header(default=None),
    x_alerting_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _enforce_auth(authorization, x_alerting_token)
    return handle_azure_eventgrid(payload, config=CONFIG)
