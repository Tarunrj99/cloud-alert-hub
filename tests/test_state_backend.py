"""State-backend tests.

The cloud-native backends (GCS / S3 / Azure Blob) are exercised against a
shared abstract harness ``_FakeObjectStoreState`` that subclasses the same
``_ObjectStoreState`` base, so we get coverage of:

* basic dedup window semantics
* concurrent-write conflict + retry path
* expiry GC keeping the blob bounded
* the ``create_state_backend`` factory routing rules and error messages

This intentionally does NOT install ``google-cloud-storage`` / ``boto3`` /
``azure-storage-blob`` in CI: we only verify the routing logic raises a
helpful ``ImportError`` if the extra is missing, and that
``_ObjectStoreState`` itself behaves correctly.
"""

from __future__ import annotations

from typing import Any

import pytest

from cloud_alert_hub.config import load_config
from cloud_alert_hub.state import (
    BaseState,
    FileState,
    InMemoryState,
    _ObjectStoreState,
    _decide_and_update,
    _utcnow,
    create_state_backend,
)


# ---------------------------------------------------------------------------
# In-memory + file backends (existing coverage)
# ---------------------------------------------------------------------------


def test_in_memory_state_dedupe() -> None:
    state: BaseState = InMemoryState()
    assert state.should_suppress("k", 600) is False
    assert state.should_suppress("k", 600) is True
    assert state.should_suppress("other", 600) is False


def test_file_state_dedupe(tmp_path) -> None:
    state_file = tmp_path / "dedupe.json"
    state = FileState(str(state_file))
    key = "cloud:project:rule"

    first = state.should_suppress(key, window_seconds=600)
    second = state.should_suppress(key, window_seconds=600)

    assert first is False
    assert second is True


def test_file_state_survives_reopen(tmp_path) -> None:
    state_file = tmp_path / "dedupe.json"
    s1 = FileState(str(state_file))
    s1.should_suppress("k", 600)

    # Simulate process restart by creating a fresh instance
    s2 = FileState(str(state_file))
    assert s2.should_suppress("k", 600) is True


# ---------------------------------------------------------------------------
# Object-store backend semantics (via in-memory fake)
# ---------------------------------------------------------------------------


class _FakeBlob:
    """In-memory stand-in for a single object in GCS/S3/Azure Blob."""

    def __init__(self) -> None:
        self.data: bytes | None = None
        self.etag: int = 0  # bumped on every successful write
        self.write_failures_remaining = 0  # for conflict-injection tests

    def get(self) -> tuple[bytes | None, int | None]:
        return (self.data, self.etag if self.data is not None else None)

    def put(self, payload: bytes, prior_etag: Any) -> bool:
        if self.write_failures_remaining > 0:
            self.write_failures_remaining -= 1
            return False
        # Optimistic-concurrency: only accept the write if prior_etag matches
        # what we currently have (None means "first writer").
        current = self.etag if self.data is not None else None
        if prior_etag is not None and prior_etag != current:
            return False
        self.data = payload
        self.etag += 1
        return True


class _FakeObjectStoreState(_ObjectStoreState):
    """Fake object-store backend that exercises the shared base class."""

    def __init__(self, blob: _FakeBlob) -> None:
        self._blob = blob

    @property
    def _locator(self) -> str:
        return "fake://bucket/object"

    def _load_blob(self) -> tuple[bytes | None, Any]:
        return self._blob.get()

    def _store_blob(self, payload: bytes, prior_etag: Any) -> bool:
        return self._blob.put(payload, prior_etag)


def test_object_store_state_first_call_persists_then_suppresses() -> None:
    blob = _FakeBlob()
    state = _FakeObjectStoreState(blob)

    assert state.should_suppress("budget:300:apr", 60) is False
    assert state.should_suppress("budget:300:apr", 60) is True
    assert blob.data is not None  # state was written


def test_object_store_state_distinguishes_keys() -> None:
    state = _FakeObjectStoreState(_FakeBlob())
    assert state.should_suppress("budget:300:apr", 60) is False
    # Different threshold or different period → not suppressed
    assert state.should_suppress("budget:310:apr", 60) is False
    assert state.should_suppress("budget:300:may", 60) is False
    # Repeat of the first key → suppressed
    assert state.should_suppress("budget:300:apr", 60) is True


def test_object_store_state_retries_on_concurrent_write_conflict() -> None:
    blob = _FakeBlob()
    blob.write_failures_remaining = 2  # two simulated conflicts before success
    state = _FakeObjectStoreState(blob)
    # Should still resolve and persist — neither suppressed nor crashed
    assert state.should_suppress("k", 60) is False
    assert blob.data is not None


def test_object_store_state_gives_up_after_too_many_conflicts() -> None:
    blob = _FakeBlob()
    blob.write_failures_remaining = 99  # never let it succeed
    state = _FakeObjectStoreState(blob)
    # Should fail-open: better to risk a duplicate alert than drop one
    assert state.should_suppress("k", 60) is False


def test_decide_and_update_garbage_collects_expired_keys() -> None:
    """Entries older than the global 90-day GC ceiling are evicted.

    The GC threshold is **fixed** (not the incoming alert's window) —
    see ``test_short_window_alert_does_not_evict_long_window_entries``
    below for the regression history. We use 200 days here to be
    well past the ceiling regardless of any future tuning.
    """
    from datetime import timedelta

    now = _utcnow()
    centuries_old = (now - timedelta(days=200)).isoformat()
    fresh = (now - timedelta(seconds=10)).isoformat()
    store = {"old:key": centuries_old, "new:key": fresh}

    suppress, fresh_store = _decide_and_update(store, "another:key", 60, now)

    assert suppress is False
    assert "old:key" not in fresh_store, "200-day-old entry should be GC'd"
    assert "new:key" in fresh_store
    assert "another:key" in fresh_store


def test_short_window_alert_does_not_evict_long_window_entries() -> None:
    """Regression: a short-window alert must NOT GC long-window entries.

    Pre-v0.5.3, ``_decide_and_update`` used ``window_seconds * 2`` as
    the GC threshold, where ``window_seconds`` was the *incoming*
    alert's window. So a 10-minute infrastructure_spike alert
    (window=600s, GC=1200s) would silently delete every other key
    older than 20 minutes — including budget entries that are
    supposed to live 32 days. In production this caused a 300%
    budget threshold to re-fire after a smoke-test infra alert wiped
    the dedup state.

    This test asserts that an entry stamped a few hours ago — well
    inside its 32-day budget window — survives a short-window alert
    arriving later.
    """
    from datetime import timedelta

    now = _utcnow()
    a_few_hours_ago = (now - timedelta(hours=4)).isoformat()
    budget_key = "gcp:proj:Apr-budget:2026-04-01T07:00:00Z:300"
    store = {budget_key: a_few_hours_ago}

    short_window = 600  # 10 minutes — typical infrastructure_spike
    suppress, fresh_store = _decide_and_update(store, "infra:cpu:75", short_window, now)

    assert suppress is False
    assert budget_key in fresh_store, (
        "long-window budget entry was evicted by a short-window infra alert; "
        "this is the v0.5.2 dedup-eviction regression"
    )
    assert "infra:cpu:75" in fresh_store


def test_decide_and_update_uses_fixed_gc_ceiling_not_incoming_window() -> None:
    """A 1-second-window alert must not evict an hour-old entry.

    Belt-and-braces companion to the regression test above: even with
    an absurdly short incoming window, GC must respect the global
    ceiling so we never evict entries the operator's other features
    still need.
    """
    from datetime import timedelta

    now = _utcnow()
    one_hour_old = (now - timedelta(hours=1)).isoformat()
    store = {"some:other:key": one_hour_old}

    suppress, fresh_store = _decide_and_update(store, "incoming:key", 1, now)

    assert suppress is False
    assert "some:other:key" in fresh_store, (
        "incoming window=1s must not GC entries an hour old; "
        "GC threshold must be a fixed ceiling, not 2 * incoming window"
    )


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def test_create_state_backend_picks_memory_by_default() -> None:
    cfg = load_config()
    assert isinstance(create_state_backend(cfg), InMemoryState)


def test_create_state_backend_picks_file_when_configured(tmp_path) -> None:
    cfg = load_config({"state": {"backend": "file", "file_path": str(tmp_path / "s.json")}})
    assert isinstance(create_state_backend(cfg), FileState)


def test_create_state_backend_unknown_backend_falls_back_to_memory() -> None:
    cfg = load_config({"state": {"backend": "nonexistent-backend"}})
    assert isinstance(create_state_backend(cfg), InMemoryState)


def test_create_state_backend_gcs_requires_bucket() -> None:
    cfg = load_config({"state": {"backend": "gcs"}})
    with pytest.raises(ValueError, match="state.bucket"):
        create_state_backend(cfg)


def test_create_state_backend_s3_requires_bucket() -> None:
    cfg = load_config({"state": {"backend": "s3"}})
    with pytest.raises(ValueError, match="state.bucket"):
        create_state_backend(cfg)


def test_create_state_backend_azure_requires_account_and_container() -> None:
    cfg = load_config({"state": {"backend": "azure_blob", "account_name": "x"}})
    with pytest.raises(ValueError, match="account_name and state.container"):
        create_state_backend(cfg)
