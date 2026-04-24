"""Ingress authentication helpers for the local-dev FastAPI server.

Cloud Function / Lambda deployments rely on cloud IAM (Pub/Sub push
authentication, EventBridge resource policies, etc.) rather than these shared
tokens — so this module is only imported when the HTTP server is running.
"""

from __future__ import annotations

import os
from typing import Any

from .config import Config


class UnauthorizedError(Exception):
    """Raised when a caller fails ingress authentication."""


def _extract_token(authorization: str | None, x_alerting_token: str | None) -> str:
    if x_alerting_token:
        return x_alerting_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def verify_ingest_token(
    config: Config,
    authorization: str | None = None,
    x_alerting_token: str | None = None,
) -> dict[str, Any]:
    """Return a result dict; raises :class:`UnauthorizedError` if auth fails."""
    if not config.ingress_auth_enabled:
        return {"authenticated": False, "enforced": False}

    provided = _extract_token(authorization, x_alerting_token)
    token_env = config.ingress_auth_token_env
    expected = os.getenv(token_env, "").strip()

    if not expected:
        raise UnauthorizedError(f"ingress_auth_enabled_but_env_{token_env}_unset")
    if provided != expected:
        raise UnauthorizedError("invalid_ingest_token")
    return {"authenticated": True, "enforced": True}
