"""End-to-end smoke tests against the public API.

Uses dry_run mode so no real HTTP calls happen.
"""

from __future__ import annotations

import json

from cloud_alert_hub import handle_aws_sns, handle_gcp_pubsub, load_config, run


def _dry_run_config(feature: str = "budget_alerts") -> dict:
    return {
        "app": {
            "environment": "test", "cloud": "gcp",
            "alerting_enabled": True, "dry_run": True, "debug_mode": True,
            "manifest": {"enabled": False},  # tests must be hermetic — no upstream fetch
        },
        "features": {feature: {"enabled": True}},
        "notifications": {
            "slack": {"enabled": True, "webhook_url_env": "SLACK_WEBHOOK_URL_TEST", "default_channel": "#test"},
            "email": {"enabled": True, "provider": "stdout"},
        },
        "routing": {
            "default_route": "finops",
            "routes": {
                "finops": {"slack_channel": "#test-finops", "email_recipients": ["qa@example.com"]},
                "security": {"slack_channel": "#test-sec", "email_recipients": []},
            },
        },
    }


def test_run_generic_budget_dry_run() -> None:
    payload = {
        "cloud": "gcp",
        "environment": "test",
        "project": "demo",
        "kind": "budget",
        "severity": "high",
        "title": "Budget 100%",
        "summary": "Test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    result = run(payload, source="generic", config=_dry_run_config())
    assert result["status"] == "processed"
    assert result["route_key"] == "finops"
    assert result["deliveries"]["slack"]["status"] == "dry_run"
    assert "debug" in result
    assert result["debug"]["trace"]["matched_feature"] == "budget_alerts"


def test_run_no_feature_claimed_is_suppressed() -> None:
    payload = {"cloud": "gcp", "kind": "unknown_kind", "title": "x", "summary": "y"}
    result = run(payload, source="generic", config=_dry_run_config())
    assert result["status"] == "suppressed"
    assert result["reason"] == "no_feature_claimed"


def test_handle_gcp_pubsub_envelope() -> None:
    import base64

    inner = {
        "kind": "budget",
        "severity": "high",
        "title": "GCP 100%",
        "summary": "from pubsub",
        "project_id": "demo",
        "environment": "test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    envelope = {
        "message": {
            "data": base64.b64encode(json.dumps(inner).encode("utf-8")).decode("ascii"),
            "attributes": {"environment": "test"},
        },
        "subscription": "projects/demo/subscriptions/x",
    }
    result = handle_gcp_pubsub(envelope, config=_dry_run_config())
    assert result["status"] == "processed"
    assert result["deliveries"]["slack"]["status"] == "dry_run"


def test_handle_aws_sns_record() -> None:
    sns_event = {
        "Records": [
            {
                "EventSource": "aws:sns",
                "Sns": {
                    "Subject": "Budget 50%",
                    "Message": json.dumps(
                        {
                            "kind": "budget",
                            "severity": "medium",
                            "title": "AWS 50%",
                            "summary": "from sns",
                            "account_id": "123",
                            "labels": {"budget_name": "demo", "threshold_percent": "50"},
                        }
                    ),
                },
            }
        ]
    }
    result = handle_aws_sns(sns_event, config=_dry_run_config())
    assert result["status"] == "processed"


def test_load_config_merges_defaults_with_user_dict() -> None:
    cfg = load_config({"app": {"environment": "qa"}})
    assert cfg.environment == "qa"
    assert cfg.default_route == "finops"
    assert "budget_alerts" in (cfg.get("features", default={}) or {})


def test_disabled_alerting_kills_delivery() -> None:
    cfg = _dry_run_config()
    cfg["app"]["alerting_enabled"] = False
    payload = {"kind": "budget", "title": "x", "summary": "y", "labels": {"threshold_percent": "100"}}
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "suppressed"
    assert result["reason"] == "global_alerting_disabled"


def _native_gcp_budget_envelope() -> dict:
    """Synthesizes a Pub/Sub envelope shaped exactly like Cloud Billing emits.

    Crucially, it carries NO ``environment`` or ``project_id`` attribute — the
    real GCP Billing service doesn't include them. The pipeline must backfill
    these from operator config so renderers don't show ``unknown``.
    """
    import base64

    native_budget = {
        "budgetDisplayName": "Demo Monthly Budget",
        "alertThresholdExceeded": 1.0,
        "costAmount": 10000,
        "budgetAmount": 10000,
        "currencyCode": "USD",
        "costIntervalStart": "2026-04-01T00:00:00Z",
        "budgetAmountType": "SPECIFIED_AMOUNT",
    }
    return {
        "message": {
            "data": base64.b64encode(json.dumps(native_budget).encode("utf-8")).decode("ascii"),
            "attributes": {"billingAccountId": "01ABCD-EFGH-IJKL"},
        },
    }


def test_native_gcp_budget_inherits_environment_from_config() -> None:
    cfg = _dry_run_config()
    cfg["app"]["environment"] = "nonprod"
    cfg["app"]["cloud"] = "gcp"
    result = handle_gcp_pubsub(_native_gcp_budget_envelope(), config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["environment"] == "nonprod"
    assert result["debug"]["alert"]["cloud"] == "gcp"


def test_native_gcp_budget_inherits_project_from_app_config() -> None:
    cfg = _dry_run_config()
    cfg["app"]["project"] = "my-team-nonprod"
    result = handle_gcp_pubsub(_native_gcp_budget_envelope(), config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["project"] == "my-team-nonprod"


def test_native_gcp_budget_falls_back_to_GOOGLE_CLOUD_PROJECT_env_var(monkeypatch) -> None:
    """When app.project is empty (the bundled default), the library should
    auto-detect the project from the runtime env var that Cloud Functions /
    Cloud Run set. This makes deployments work with zero config edits."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "auto-detected-project")
    cfg = _dry_run_config()
    cfg["app"].pop("project", None)
    result = handle_gcp_pubsub(_native_gcp_budget_envelope(), config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["project"] == "auto-detected-project"


def test_explicit_environment_in_payload_wins_over_config() -> None:
    """If the upstream payload explicitly sets environment, config must not override it."""
    cfg = _dry_run_config()
    cfg["app"]["environment"] = "nonprod"
    payload = {
        "cloud": "gcp",
        "environment": "staging",
        "kind": "budget",
        "title": "Budget 100%",
        "summary": "Test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["environment"] == "staging"


def test_manifest_block_aborts_delivery_end_to_end(monkeypatch) -> None:
    """Integration test for the runtime manifest (a.k.a. killswitch).

    Unit tests in ``test_manifest.py`` cover the various ways
    :func:`check_manifest` can return ``allow=False`` (404 from
    GitHub, paused status, deprecated version, deployment override,
    network error in strict mode, etc.). This test bolts that
    behaviour to the public API to guarantee the integration: if the
    manifest verdict is ``allow=False`` for any reason, ``run()`` must
    return a fully-formed ``suppressed`` result, never call any
    notifier, and surface the manifest reason in the trace.

    Without this test, a future refactor could move ``check_manifest``
    out of the policy chain and silently break the killswitch.
    """
    from cloud_alert_hub import policy as policy_module
    from cloud_alert_hub.manifest import ManifestStatus

    def _fake_check_manifest(_cfg, *, deployment_id=None):  # noqa: ARG001
        return ManifestStatus(
            allow=False,
            reason="manifest_test_blocked",
            source="remote",
            fetched_at=0.0,
            descriptor={"runtime_status": "paused"},
        )

    monkeypatch.setattr(policy_module, "check_manifest", _fake_check_manifest)

    cfg = _dry_run_config()
    # Even with manifest enabled and a URL configured, the patched
    # check_manifest returns allow=False — proving the policy honours it
    # regardless of how the verdict was produced.
    cfg["app"]["manifest"] = {
        "enabled": True,
        "url": "https://example.invalid/manifest.json",
    }
    payload = {
        "cloud": "gcp",
        "kind": "budget",
        "title": "Budget 100%",
        "summary": "should never reach Slack",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }

    result = run(payload, source="generic", config=cfg)

    assert result["status"] == "suppressed"
    assert result["reason"] == "manifest_test_blocked"
    # No delivery attempt, not even a dry_run one.
    assert "deliveries" not in result or result["deliveries"] == {}
    # Trace must record manifest verdict for audit / debugging.
    assert "debug" in result
    manifest_trace = result["debug"]["trace"]["manifest"]
    assert manifest_trace["allow"] is False
    assert manifest_trace["reason"] == "manifest_test_blocked"


def test_manifest_disabled_does_not_block_delivery() -> None:
    """The mirror of :func:`test_manifest_block_aborts_delivery_end_to_end`.

    Confirms that when the manifest is *off* (the default for unit
    tests — see ``_dry_run_config``), the policy chain proceeds
    normally. This guards against an over-eager manifest implementation
    accidentally rejecting alerts in deployments that haven't opted in.
    """
    cfg = _dry_run_config()
    cfg["app"]["manifest"] = {"enabled": False}
    payload = {
        "cloud": "gcp",
        "kind": "budget",
        "title": "Budget 50%",
        "summary": "manifest-off should still deliver",
        "labels": {"budget_name": "demo", "threshold_percent": "50"},
    }
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["trace"]["manifest"]["allow"] is True
    assert result["debug"]["trace"]["manifest"]["source"] == "disabled"


# ---------------------------------------------------------------------------
# Per-lever runtime-control scenarios.
#
# The runtime manifest is the operator's only remote lever for stopping
# alerts after they've been deployed (no SSH, no IAM change, no redeploy
# needed — just edit one JSON file in the public repo). It exposes four
# independent "knobs" that an operator can flip; each maps to a distinct
# real-world incident response.
#
# These tests bolt every knob to the public ``run()`` API so we have
# pinned proof that flipping the knob in production actually short-
# circuits ``run()`` for every shipped feature. The unit tests in
# ``tests/test_manifest.py`` cover the decision function in isolation;
# these cover the *integration* with the policy chain.
#
# Naming convention: ``test_runtime_control_lever_<N>_<scenario>`` so a
# future operator can grep for ``runtime_control`` and immediately see
# every knob this library exposes for stopping alerts at runtime.
# ---------------------------------------------------------------------------


def _make_fake_http_factory(status_code: int, body):
    """Return a callable that produces a context-manager fake httpx
    client serving a single response. Mirrors the helper in
    ``tests/test_manifest.py``."""
    import json as _json

    import httpx

    if isinstance(body, dict):
        body_bytes = _json.dumps(body).encode()
        ctype = "application/json"
    else:
        body_bytes = body.encode()
        ctype = "text/plain"

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, _url):
            return httpx.Response(
                status_code=status_code,
                headers={"content-type": ctype},
                content=body_bytes,
            )

    return _FakeClient


def _patch_manifest_with_fake_http(monkeypatch, status_code: int, body) -> None:
    """Patch ``policy.check_manifest`` so it calls the real
    ``check_manifest`` but with a fake HTTP factory injected — this lets
    every per-lever integration test below exercise the real decision
    logic in ``manifest.py`` without making a real network call.
    """
    from cloud_alert_hub import manifest as manifest_module
    from cloud_alert_hub import policy as policy_module

    factory = _make_fake_http_factory(status_code, body)

    def _wrapped(cfg, *, deployment_id=None):
        return manifest_module.check_manifest(
            cfg, deployment_id=deployment_id, http_client_factory=factory
        )

    monkeypatch.setattr(policy_module, "check_manifest", _wrapped)


def _dry_run_payload(threshold: str = "50") -> dict:
    return {
        "cloud": "gcp",
        "kind": "budget",
        "title": "Budget event",
        "summary": "should be evaluated against the manifest",
        "labels": {"budget_name": "demo", "threshold_percent": threshold},
    }


def _runtime_control_config() -> dict:
    cfg = _dry_run_config()
    cfg["app"]["manifest"] = {
        "enabled": True,
        "url": "https://example.invalid/.manifest.json",
        # Disable cache so each test sees a fresh fetch.
        "refresh_interval_seconds": 0,
        # Strict mode where useful (default is permissive on network err).
    }
    return cfg


def test_runtime_control_lever_1_global_pause_stops_every_alert(monkeypatch) -> None:
    """Lever 1: ``service_status: "paused"`` halts every alert globally.

    Operator scenario: an unforeseen alert storm or compromised Slack
    workspace. Operator edits ``.manifest.json`` on GitHub, sets
    ``service_status: "paused"``. Within one cache TTL every deployed
    function calls ``check_manifest`` → sees ``paused`` → ``run()``
    short-circuits with reason ``service_status_inactive``. No notifier
    is invoked.
    """
    from cloud_alert_hub.manifest import reset_cache

    reset_cache()
    _patch_manifest_with_fake_http(monkeypatch, 200, {"service_status": "paused"})

    result = run(_dry_run_payload(), source="generic", config=_runtime_control_config())
    assert result["status"] == "suppressed"
    assert result["reason"] == "service_status_inactive"
    assert result["debug"]["trace"]["manifest"]["source"] == "remote"
    assert "deliveries" not in result or result["deliveries"] == {}


def test_runtime_control_lever_2_deprecated_version_stops_just_that_version(monkeypatch) -> None:
    """Lever 2: ``deprecated_versions: ["X.Y.Z"]`` halts alerts only for
    deployments running exactly version X.Y.Z.

    Operator scenario: a buggy release shipped, a fix is in flight,
    operator wants to stop the buggy version without touching deployments
    on a known-good version. Adds the exact version string to
    ``deprecated_versions`` and commits.
    """
    from cloud_alert_hub.manifest import _installed_version, reset_cache

    reset_cache()
    _patch_manifest_with_fake_http(
        monkeypatch,
        200,
        {
            "service_status": "active",
            "deprecated_versions": [_installed_version()],
        },
    )

    result = run(_dry_run_payload(), source="generic", config=_runtime_control_config())
    assert result["status"] == "suppressed"
    assert result["reason"] == "version_unsupported"


def test_runtime_control_lever_3_per_deployment_override_is_surgical(monkeypatch) -> None:
    """Lever 3: ``deployment_overrides`` halts a single deployment by id.

    Operator scenario: one team's deployment is misbehaving (e.g. wrong
    Slack webhook, runaway dedup) and we want to stop it without
    affecting any other team that's pip-installed the library. Operator
    adds ``{"deployment_id": "<their id>", "status": "disabled"}`` to
    the manifest. Only that deployment short-circuits.
    """
    from cloud_alert_hub.manifest import reset_cache

    reset_cache()
    _patch_manifest_with_fake_http(
        monkeypatch,
        200,
        {
            "service_status": "active",
            "deployment_overrides": [
                {"deployment_id": "some-team-deployment", "status": "disabled"},
            ],
        },
    )

    cfg = _runtime_control_config()
    cfg["app"]["deployment_id"] = "some-team-deployment"
    result = run(_dry_run_payload(), source="generic", config=cfg)
    assert result["status"] == "suppressed"
    assert result["reason"] == "deployment_disabled"

    # Mirror: another deployment id is unaffected by the same override.
    reset_cache()
    cfg2 = _runtime_control_config()
    cfg2["app"]["deployment_id"] = "another-deployment"
    result2 = run(_dry_run_payload(), source="generic", config=cfg2)
    assert result2["status"] == "processed"


def test_runtime_control_lever_4_repo_unreachable_fails_closed(monkeypatch) -> None:
    """Lever 4: making the manifest URL unreachable (private repo, deleted
    file, deleted repo, renamed repo) is the most permanent stop.

    Operator scenario: catastrophic compromise where the operator has
    lost confidence in the library entirely and wants every deployment
    halted without an audit trail of edits to ``.manifest.json``.
    Setting the GitHub repo to private (or deleting the file) makes
    every authenticated/unauthenticated GET return 404. Default
    behaviour is fail-closed → ``run()`` short-circuits with reason
    ``manifest_unavailable``.
    """
    from cloud_alert_hub.manifest import reset_cache

    reset_cache()
    _patch_manifest_with_fake_http(monkeypatch, 404, "Not Found")

    result = run(_dry_run_payload(), source="generic", config=_runtime_control_config())
    assert result["status"] == "suppressed"
    assert result["reason"] == "manifest_unavailable"
    assert result["debug"]["trace"]["manifest"]["source"] == "rejected"


def test_runtime_control_paused_then_active_round_trip(monkeypatch) -> None:
    """The operational round-trip: pause → verify suppressed → un-pause →
    verify alerts resume.

    This is the realistic incident-response loop: stop the alerts to
    investigate, then turn them back on once the issue is resolved.
    Without this test, a refactor could break the cache-invalidation
    path that lets ``active`` win after ``paused`` (the cached
    ``paused`` verdict must be replaced, not preserved).
    """
    from cloud_alert_hub.manifest import reset_cache

    reset_cache()
    cfg = _runtime_control_config()

    _patch_manifest_with_fake_http(monkeypatch, 200, {"service_status": "paused"})
    paused = run(_dry_run_payload("50"), source="generic", config=cfg)
    assert paused["status"] == "suppressed"
    assert paused["reason"] == "service_status_inactive"

    reset_cache()  # simulate cache TTL expiring before the next event
    _patch_manifest_with_fake_http(monkeypatch, 200, {"service_status": "active"})
    resumed = run(_dry_run_payload("70"), source="generic", config=cfg)
    assert resumed["status"] == "processed", (
        "Alerts must resume after the manifest flips back to active. If "
        "this fails, inspect the cache invalidation path in "
        "manifest.py — the previous 'paused' verdict may be sticky."
    )


def test_explicit_project_in_payload_wins_over_config(monkeypatch) -> None:
    """A canonical payload with an explicit project_id must not be clobbered
    by either app.project config or the runtime env var fallback."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "should-not-be-used")
    cfg = _dry_run_config()
    cfg["app"]["project"] = "also-should-not-be-used"
    payload = {
        "cloud": "gcp",
        "environment": "nonprod",
        "project": "explicit-from-payload",
        "kind": "budget",
        "title": "Budget 100%",
        "summary": "Test",
        "labels": {"budget_name": "demo", "threshold_percent": "100"},
    }
    result = run(payload, source="generic", config=cfg)
    assert result["status"] == "processed"
    assert result["debug"]["alert"]["project"] == "explicit-from-payload"
