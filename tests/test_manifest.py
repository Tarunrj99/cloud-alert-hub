"""Tests for the runtime manifest check.

Each test injects a fake HTTP client factory so no real network calls are
made. The cache is reset between tests for independence.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from cloud_alert_hub.manifest import check_manifest, reset_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_cache()


def _factory_returning(status_code: int, body: dict[str, Any] | str) -> Any:
    body_bytes = (
        json.dumps(body).encode() if isinstance(body, dict) else body.encode()
    )
    content_type = "application/json" if isinstance(body, dict) else "text/plain"

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def get(self, url: str) -> httpx.Response:  # noqa: ARG002
            return httpx.Response(
                status_code=status_code,
                headers={"content-type": content_type},
                content=body_bytes,
            )

    return _FakeClient


def _factory_raising(exc: Exception) -> Any:
    class _Boom:
        def __enter__(self) -> "_Boom":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def get(self, url: str) -> httpx.Response:  # noqa: ARG002
            raise exc

    return _Boom


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------

def test_disabled_check_short_circuits() -> None:
    status = check_manifest({"enabled": False}, http_client_factory=None)
    assert status.allow is True
    assert status.source == "disabled"


def test_active_status_allows() -> None:
    cfg = {"enabled": True, "url": "https://example.test/.manifest.json"}
    factory = _factory_returning(200, {"service_status": "active", "min_supported_version": "0.0.1"})
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is True
    assert status.source == "remote"


def test_inactive_status_blocks() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(200, {"service_status": "paused"})
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False
    assert status.reason == "service_status_inactive"


def test_deprecated_status_also_blocks() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(200, {"service_status": "deprecated"})
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False


def test_deprecated_version_blocks() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    from cloud_alert_hub.manifest import _installed_version  # type: ignore[attr-defined]
    version = _installed_version()
    factory = _factory_returning(
        200, {"service_status": "active", "deprecated_versions": [version]}
    )
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False
    assert status.reason == "version_unsupported"


def test_deployment_override_blocks() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(
        200,
        {
            "service_status": "active",
            "deployment_overrides": [
                {"deployment_id": "test-nonprod", "status": "disabled"}
            ],
        },
    )
    status = check_manifest(cfg, deployment_id="test-nonprod", http_client_factory=factory)
    assert status.allow is False
    assert status.reason == "deployment_disabled"


def test_min_version_below_installed_blocks() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(
        200, {"service_status": "active", "min_supported_version": "999.0.0"}
    )
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False
    assert status.reason == "version_unsupported"


# ---------------------------------------------------------------------------
# 4xx — repo gone / private / file removed
# ---------------------------------------------------------------------------

def test_404_default_rejects() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(404, "Not Found")
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False
    assert status.reason == "manifest_unavailable"
    assert status.source == "rejected"


def test_404_tolerated_when_configured() -> None:
    cfg = {
        "enabled": True,
        "url": "https://example.test/x.json",
        "tolerate_missing_manifest": True,
    }
    factory = _factory_returning(404, "Not Found")
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is True
    assert status.source == "tolerated"


def test_403_treated_like_404() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(403, "Forbidden")
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False


# ---------------------------------------------------------------------------
# transient errors
# ---------------------------------------------------------------------------

def test_network_error_with_no_cache_tolerates_by_default() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_raising(httpx.ConnectError("boom"))
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is True
    assert status.source == "tolerated"


def test_network_error_can_be_strict() -> None:
    cfg = {
        "enabled": True,
        "url": "https://example.test/x.json",
        "tolerate_network_errors": False,
    }
    factory = _factory_raising(httpx.ConnectError("boom"))
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False
    assert status.source == "rejected"


def test_network_error_uses_cache_after_ttl() -> None:
    cfg = {
        "enabled": True,
        "url": "https://example.test/x.json",
        "refresh_interval_seconds": 60,
    }
    ok = _factory_returning(200, {"service_status": "active"})
    first = check_manifest(cfg, http_client_factory=ok, now=1000.0)
    assert first.allow is True

    boom = _factory_raising(httpx.ConnectError("boom"))
    second = check_manifest(cfg, http_client_factory=boom, now=1010.0)
    assert second.allow is True
    assert second.source == "remote"  # served from in-process cache

    third = check_manifest(cfg, http_client_factory=boom, now=2000.0)
    assert third.allow is True
    assert third.source == "cached"


# ---------------------------------------------------------------------------
# cache TTL behaviour
# ---------------------------------------------------------------------------

def test_cache_reused_within_ttl() -> None:
    cfg = {
        "enabled": True,
        "url": "https://example.test/x.json",
        "refresh_interval_seconds": 100,
    }
    calls: list[str] = []

    class _CountingFactory:
        def __init__(self) -> None:
            self.body = json.dumps({"service_status": "active"}).encode()

        def __call__(self) -> "_CountingFactory":
            return self

        def __enter__(self) -> "_CountingFactory":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def get(self, url: str) -> httpx.Response:
            calls.append(url)
            return httpx.Response(
                status_code=200,
                headers={"content-type": "application/json"},
                content=self.body,
            )

    factory = _CountingFactory()
    check_manifest(cfg, http_client_factory=factory, now=1000.0)
    check_manifest(cfg, http_client_factory=factory, now=1050.0)
    check_manifest(cfg, http_client_factory=factory, now=1099.0)
    assert len(calls) == 1, "expected only one fetch within the TTL"

    check_manifest(cfg, http_client_factory=factory, now=1101.0)
    assert len(calls) == 2, "expected a re-fetch after TTL expires"


def test_non_json_body_default_tolerates() -> None:
    cfg = {"enabled": True, "url": "https://example.test/x.json"}
    factory = _factory_returning(200, "not actually json")
    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is True


def test_missing_url_tolerates() -> None:
    cfg = {"enabled": True, "url": ""}
    status = check_manifest(cfg, http_client_factory=None)
    assert status.allow is True
    assert status.source == "tolerated"


def test_github_contents_api_base64_envelope_is_unwrapped() -> None:
    """GitHub's Contents API wraps the file in a base64 envelope. The fetcher
    should unwrap it transparently and behave the same as a raw JSON URL."""
    import base64

    cfg = {"enabled": True, "url": "https://api.example.test/contents/.manifest.json"}
    inner = json.dumps({"service_status": "paused"}).encode()
    envelope = {
        "name": ".manifest.json",
        "encoding": "base64",
        "content": base64.b64encode(inner).decode(),
    }
    factory = _factory_returning(200, envelope)

    status = check_manifest(cfg, http_client_factory=factory)
    assert status.allow is False
    assert status.reason == "service_status_inactive"
