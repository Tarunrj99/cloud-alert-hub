"""Deduplication state stores.

Two backends ship by default:

* :class:`InMemoryState` — resets per process. Fine for Cloud Functions and
  Lambdas because the cloud provider already dedupes Pub/Sub / SNS messages
  at the infrastructure layer.
* :class:`FileState` — JSON file on local disk. Useful for long-lived
  containers or the local-dev FastAPI example.

Add a Redis / Firestore / DynamoDB backend by subclassing :class:`BaseState`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from .config import Config


class BaseState(ABC):
    @abstractmethod
    def should_suppress(self, key: str, window_seconds: int) -> bool:
        raise NotImplementedError


class InMemoryState(BaseState):
    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}

    def should_suppress(self, key: str, window_seconds: int) -> bool:
        now = datetime.now(timezone.utc)
        previous = self._seen.get(key)
        if previous and (now - previous) < timedelta(seconds=window_seconds):
            return True
        self._seen[key] = now
        return False


class FileState(BaseState):
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
            now = datetime.now(timezone.utc)
            store = self._read()
            last_seen_raw = store.get(key)
            if last_seen_raw:
                try:
                    last_seen = datetime.fromisoformat(last_seen_raw)
                except ValueError:
                    last_seen = None
                if last_seen and (now - last_seen) < timedelta(seconds=window_seconds):
                    return True
            store[key] = now.isoformat()
            self._write(store)
        return False


def create_state_backend(config: Config) -> BaseState:
    if config.state_backend == "file":
        return FileState(file_path=config.state_file_path)
    return InMemoryState()
