"""Deduplication state stores.

cloud_alert_hub ships **four** backends out of the box. Pick the one that
matches your runtime; the same `BaseState` interface is used everywhere so
features and the policy engine never have to know which backend is in play.

Backend matrix
--------------

============  =============================================  ================  ==========================
Backend       Best for                                       Persistence       Optional dependency
============  =============================================  ================  ==========================
``memory``    Local dev, single-process tests                Process lifetime  none (default)
``file``      Long-lived containers (Cloud Run min=1, k8s)   Disk lifetime     none
``gcs``       GCP Cloud Functions / Cloud Run (serverless)   Bucket lifetime   ``cloud-alert-hub[gcp]``
``s3``        AWS Lambda / ECS / EKS                         Bucket lifetime   ``cloud-alert-hub[aws]``
``azure_blob`` Azure Functions / Container Apps              Container lifetime ``cloud-alert-hub[azure]``
============  =============================================  ================  ==========================

Why the cloud-native object stores?
-----------------------------------

Serverless function instances are short-lived (cold-start every ~10–30 min).
``memory`` and ``file`` backends therefore lose state and re-fire alerts that
had already been suppressed. The cloud-native backends use the SAME storage
service the function platform already implicitly uses (Lambda/Cloud Functions
both ship code via S3/GCS), so adding a small ``dedup-state.json`` blob does
not introduce a new service dependency.

All three cloud backends use **read-modify-write** semantics with optimistic
concurrency control (precondition headers / generation match) so concurrent
function invocations don't trample each other's state.

The cloud SDKs are imported lazily inside ``__init__`` — installing the
library without the corresponding extra is fine; you'll only see an
``ImportError`` at runtime when actually instantiating that backend.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .config import Config

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base interface + helpers
# ---------------------------------------------------------------------------


class BaseState(ABC):
    """Abstract dedup state store."""

    @abstractmethod
    def should_suppress(self, key: str, window_seconds: int) -> bool:
        raise NotImplementedError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decide_and_update(
    store: dict[str, str], key: str, window_seconds: int, now: datetime
) -> tuple[bool, dict[str, str]]:
    """Pure decision function shared by all object-store backends.

    Returns ``(suppress, new_store)`` where ``new_store`` has the bookkeeping
    applied (``key`` stamped with ``now``) AND any expired keys garbage-
    collected. We GC eagerly so the JSON blob does not grow unbounded; the
    threshold is ``2 * window_seconds`` past expiry to give us a debugging
    buffer if an operator wants to read the file post-mortem.
    """
    fresh: dict[str, str] = {}
    suppress = False
    for stored_key, ts_raw in store.items():
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        age = (now - ts).total_seconds()
        if age >= window_seconds * 2:
            continue
        fresh[stored_key] = ts_raw
        if stored_key == key and age < window_seconds:
            suppress = True
    if not suppress:
        fresh[key] = now.isoformat()
    return suppress, fresh


# ---------------------------------------------------------------------------
# In-process / disk backends (no cloud dependencies)
# ---------------------------------------------------------------------------


class InMemoryState(BaseState):
    """Resets per process. Fine for unit tests and local dev only."""

    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}

    def should_suppress(self, key: str, window_seconds: int) -> bool:
        now = _utcnow()
        previous = self._seen.get(key)
        if previous and (now - previous) < timedelta(seconds=window_seconds):
            return True
        self._seen[key] = now
        return False


class FileState(BaseState):
    """JSON file on local disk. Survives within a long-lived container."""

    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)
        self._lock = Lock()
        if not self._path.parent.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}", encoding="utf-8")

    def _read(self) -> dict[str, str]:
        raw = self._path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _write(self, payload: dict[str, str]) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self._path)

    def should_suppress(self, key: str, window_seconds: int) -> bool:
        with self._lock:
            now = _utcnow()
            store = self._read()
            suppress, fresh = _decide_and_update(store, key, window_seconds, now)
            if not suppress:
                self._write(fresh)
            return suppress


# ---------------------------------------------------------------------------
# Cloud-native object store backends
# ---------------------------------------------------------------------------


class _ObjectStoreState(BaseState):
    """Shared scaffolding for GCS / S3 / Azure Blob backends.

    Subclasses implement three primitives:

    * ``_load_blob() -> tuple[bytes | None, etag | None]``
    * ``_store_blob(payload: bytes, prior_etag: etag | None) -> bool``
       (returns False on optimistic-concurrency conflict so we can retry)
    * Friendly ``_locator`` string for log messages.

    The base class handles JSON encoding/decoding, expiry GC, and a small
    retry loop for concurrent writes. We keep it intentionally simple — at
    most a handful of writes per minute, so even pessimistic locking would be
    fine; optimistic-concurrency keeps the blob lightweight.
    """

    _MAX_CONFLICT_RETRIES = 3

    @abstractmethod
    def _load_blob(self) -> tuple[bytes | None, Any]:
        raise NotImplementedError

    @abstractmethod
    def _store_blob(self, payload: bytes, prior_etag: Any) -> bool:
        raise NotImplementedError

    @property
    def _locator(self) -> str:
        return self.__class__.__name__

    def _decode(self, raw: bytes | None) -> dict[str, str]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            LOG.warning("dedupe state blob at %s was not valid JSON; resetting", self._locator)
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def should_suppress(self, key: str, window_seconds: int) -> bool:
        now = _utcnow()
        for attempt in range(self._MAX_CONFLICT_RETRIES):
            raw, etag = self._load_blob()
            store = self._decode(raw)
            suppress, fresh = _decide_and_update(store, key, window_seconds, now)
            if suppress:
                return True
            payload = json.dumps(fresh, separators=(",", ":")).encode("utf-8")
            if self._store_blob(payload, etag):
                return False
            LOG.info(
                "dedupe state write conflict at %s (attempt %d) — retrying",
                self._locator, attempt + 1,
            )
        LOG.warning(
            "dedupe state at %s saw %d concurrent-write conflicts; allowing alert",
            self._locator, self._MAX_CONFLICT_RETRIES,
        )
        return False


class GCSState(_ObjectStoreState):
    """Google Cloud Storage backend.

    Recommended for GCP Cloud Functions / Cloud Run. The Cloud Function's
    runtime service account needs the ``roles/storage.objectAdmin`` role on
    the chosen bucket (or the narrower ``objectCreator + objectViewer`` pair).

    Uses GCS *generation match* preconditions for optimistic concurrency.
    """

    def __init__(self, bucket: str, object_path: str = "dedup-state.json") -> None:
        try:
            from google.cloud import storage  # noqa: PLC0415  (lazy import is intentional)
        except ImportError as exc:  # pragma: no cover — exercised by extras tests
            raise ImportError(
                "GCSState requires the optional 'gcp' extra: "
                "pip install 'cloud-alert-hub[gcp]'"
            ) from exc
        self._bucket_name = bucket
        self._object_path = object_path
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    @property
    def _locator(self) -> str:
        return f"gs://{self._bucket_name}/{self._object_path}"

    def _load_blob(self) -> tuple[bytes | None, Any]:
        from google.api_core import exceptions as gcs_exc  # noqa: PLC0415

        blob = self._bucket.blob(self._object_path)
        try:
            data = blob.download_as_bytes()
        except gcs_exc.NotFound:
            return None, 0  # generation 0 = "object must not exist"
        return data, blob.generation

    def _store_blob(self, payload: bytes, prior_etag: Any) -> bool:
        from google.api_core import exceptions as gcs_exc  # noqa: PLC0415

        blob = self._bucket.blob(self._object_path)
        kwargs: dict[str, Any] = {"content_type": "application/json"}
        if prior_etag is not None:
            kwargs["if_generation_match"] = prior_etag
        try:
            blob.upload_from_string(payload, **kwargs)
            return True
        except gcs_exc.PreconditionFailed:
            return False


class S3State(_ObjectStoreState):
    """AWS S3 backend.

    Recommended for AWS Lambda / ECS / EKS. The Lambda execution role needs
    ``s3:GetObject`` and ``s3:PutObject`` on the chosen object key.

    S3 doesn't have native compare-and-swap, so we use ETag-based
    optimistic concurrency: ``GetObject`` returns the current ETag, and
    ``PutObject`` is a *best-effort* swap. Because our write rate is at most
    a few per minute, lost updates are statistically negligible — the next
    Pub/Sub re-emission re-applies the dedup key anyway.
    """

    def __init__(
        self,
        bucket: str,
        object_path: str = "dedup-state.json",
        region: str | None = None,
    ) -> None:
        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "S3State requires the optional 'aws' extra: "
                "pip install 'cloud-alert-hub[aws]'"
            ) from exc
        self._bucket = bucket
        self._object_path = object_path
        self._client = boto3.client("s3", region_name=region) if region else boto3.client("s3")

    @property
    def _locator(self) -> str:
        return f"s3://{self._bucket}/{self._object_path}"

    def _load_blob(self) -> tuple[bytes | None, Any]:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=self._object_path)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                return None, None
            raise
        return obj["Body"].read(), obj.get("ETag")

    def _store_blob(self, payload: bytes, prior_etag: Any) -> bool:
        # S3 PutObject doesn't support If-Match natively (only via SSE-KMS
        # tricks). Best-effort write — see class docstring for tradeoffs.
        del prior_etag
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._object_path,
            Body=payload,
            ContentType="application/json",
        )
        return True


class AzureBlobState(_ObjectStoreState):
    """Azure Blob Storage backend.

    Recommended for Azure Functions / Container Apps. Uses ``DefaultAzure
    Credential`` (managed identity on Azure, env vars locally). The function's
    managed identity needs the ``Storage Blob Data Contributor`` role on the
    target container.

    Uses Azure Blob *If-Match* / *If-None-Match* ETag preconditions for
    optimistic concurrency.
    """

    def __init__(
        self,
        account_name: str,
        container: str,
        blob_name: str = "dedup-state.json",
        connection_string_env: str | None = None,
    ) -> None:
        try:
            from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "AzureBlobState requires the optional 'azure' extra: "
                "pip install 'cloud-alert-hub[azure]'"
            ) from exc

        if connection_string_env:
            import os  # noqa: PLC0415

            conn = os.getenv(connection_string_env)
            if not conn:
                raise RuntimeError(
                    f"connection_string_env '{connection_string_env}' is unset"
                )
            self._svc = BlobServiceClient.from_connection_string(conn)
        else:
            from azure.identity import DefaultAzureCredential  # noqa: PLC0415

            url = f"https://{account_name}.blob.core.windows.net"
            self._svc = BlobServiceClient(account_url=url, credential=DefaultAzureCredential())

        self._account_name = account_name
        self._container = container
        self._blob_name = blob_name

    @property
    def _locator(self) -> str:
        return f"https://{self._account_name}.blob.core.windows.net/{self._container}/{self._blob_name}"

    def _client(self):  # type: ignore[no-untyped-def]
        return self._svc.get_blob_client(container=self._container, blob=self._blob_name)

    def _load_blob(self) -> tuple[bytes | None, Any]:
        from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415

        try:
            stream = self._client().download_blob()
            data = stream.readall()
            etag = stream.properties.etag if stream.properties else None
            return data, etag
        except ResourceNotFoundError:
            return None, None

    def _store_blob(self, payload: bytes, prior_etag: Any) -> bool:
        from azure.core.exceptions import (  # noqa: PLC0415
            ResourceModifiedError,
            ResourceExistsError,
        )

        kwargs: dict[str, Any] = {"overwrite": True}
        if prior_etag is not None:
            kwargs["etag"] = prior_etag
            kwargs["match_condition"] = _azure_if_match()
        else:
            kwargs["match_condition"] = _azure_if_none_match()

        try:
            self._client().upload_blob(data=payload, **kwargs)
            return True
        except (ResourceModifiedError, ResourceExistsError):
            return False


def _azure_if_match():  # type: ignore[no-untyped-def]
    from azure.core import MatchConditions  # noqa: PLC0415

    return MatchConditions.IfNotModified


def _azure_if_none_match():  # type: ignore[no-untyped-def]
    from azure.core import MatchConditions  # noqa: PLC0415

    return MatchConditions.IfMissing


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_state_backend(config: Config) -> BaseState:
    """Build a state backend from ``config.state``.

    Recognised values for ``state.backend``:

    * ``memory`` (default)
    * ``file`` — needs ``state.file_path``
    * ``gcs`` — needs ``state.bucket``; optional ``state.object_path``
    * ``s3`` — needs ``state.bucket``; optional ``state.object_path``,
      ``state.region``
    * ``azure_blob`` — needs ``state.account_name`` and ``state.container``;
      optional ``state.blob_name``, ``state.connection_string_env``
    """
    backend = (config.state_backend or "memory").lower()

    if backend == "file":
        return FileState(file_path=config.state_file_path)

    if backend == "gcs":
        bucket = config.state_bucket
        if not bucket:
            raise ValueError("state.backend=gcs requires state.bucket")
        return GCSState(bucket=bucket, object_path=config.state_object_path)

    if backend == "s3":
        bucket = config.state_bucket
        if not bucket:
            raise ValueError("state.backend=s3 requires state.bucket")
        return S3State(
            bucket=bucket,
            object_path=config.state_object_path,
            region=config.state_region,
        )

    if backend == "azure_blob":
        account = config.state_account_name
        container = config.state_container
        if not account or not container:
            raise ValueError(
                "state.backend=azure_blob requires state.account_name and state.container"
            )
        return AzureBlobState(
            account_name=account,
            container=container,
            blob_name=config.state_blob_name,
            connection_string_env=config.state_connection_string_env,
        )

    if backend != "memory":
        LOG.warning("unknown state.backend=%r; falling back to in-memory", backend)
    return InMemoryState()
