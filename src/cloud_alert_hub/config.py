"""Configuration loader for cloud_alert_hub.

Resolution order (later wins):
    1. Bundled defaults (shipped with the package).
    2. User config — a dict, a path to a YAML file, or a YAML string.
    3. Environment variable overrides (selected keys only).

Keep config.yaml free of secrets. Secrets stay in environment variables; the
YAML only names the env var.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _read_yaml_string(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_bundled_defaults() -> dict[str, Any]:
    """Load the defaults YAML that ships inside the package."""
    try:
        text = resources.files(__package__).joinpath("bundled_defaults.yaml").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        fallback = Path(__file__).parent / "bundled_defaults.yaml"
        text = fallback.read_text(encoding="utf-8") if fallback.exists() else ""
    return _read_yaml_string(text) if text else {}


def _coerce_user_config(user_config: Any) -> dict[str, Any]:
    """Accept a dict, a filesystem path, a Path, or a YAML string."""
    if user_config is None:
        return {}
    if isinstance(user_config, dict):
        return user_config
    if isinstance(user_config, Path):
        return _read_yaml_file(user_config)
    if isinstance(user_config, str):
        candidate = Path(user_config)
        if candidate.suffix in {".yaml", ".yml"} and candidate.exists():
            return _read_yaml_file(candidate)
        return _read_yaml_string(user_config)
    raise TypeError(f"Unsupported config type: {type(user_config)!r}")


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Let a small set of env vars override config values without needing YAML edits.

    Useful in CI/CD where the same artifact is promoted across environments.
    """
    env_map = {
        "APP_ENV": ("app", "environment"),
        "APP_CLOUD": ("app", "cloud"),
        "ALERTING_ENABLED": ("app", "alerting_enabled"),
        "DRY_RUN": ("app", "dry_run"),
        "DEBUG_MODE": ("app", "debug_mode"),
        "DEPLOYMENT_ID": ("app", "deployment_id"),
        "CLOUD_ALERT_HUB_MANIFEST_ENABLED": ("app", "manifest", "enabled"),
        "CLOUD_ALERT_HUB_MANIFEST_URL": ("app", "manifest", "url"),
        "CLOUD_ALERT_HUB_MANIFEST_REFRESH": ("app", "manifest", "refresh_interval_seconds"),
        "DEFAULT_ROUTE": ("routing", "default_route"),
        "STATE_BACKEND": ("state", "backend"),
        "STATE_FILE_PATH": ("state", "file_path"),
        "STATE_BUCKET": ("state", "bucket"),
        "STATE_OBJECT_PATH": ("state", "object_path"),
        "STATE_REGION": ("state", "region"),
        "STATE_ACCOUNT_NAME": ("state", "account_name"),
        "STATE_CONTAINER": ("state", "container"),
        "STATE_BLOB_NAME": ("state", "blob_name"),
    }
    result = dict(config)
    for env_var, path in env_map.items():
        raw = os.getenv(env_var)
        if raw is None:
            continue
        value: Any = raw
        if raw.lower() in {"true", "false"}:
            value = raw.lower() == "true"
        elif raw.lstrip("-").isdigit():
            value = int(raw)
        cursor = result
        for key in path[:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[path[-1]] = value
    return result


class Config:
    """Resolved configuration. Read-only accessors are provided as properties."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    # ---- raw access ---------------------------------------------------------

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    def get(self, *path: str, default: Any = None) -> Any:
        cursor: Any = self._raw
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                return default
            cursor = cursor[key]
        return cursor

    # ---- app ---------------------------------------------------------------

    @property
    def environment(self) -> str:
        return str(self.get("app", "environment", default="unknown"))

    @property
    def cloud(self) -> str:
        return str(self.get("app", "cloud", default="unknown"))

    @property
    def alerting_enabled(self) -> bool:
        return bool(self.get("app", "alerting_enabled", default=True))

    @property
    def dry_run(self) -> bool:
        return bool(self.get("app", "dry_run", default=False))

    @property
    def debug_mode(self) -> bool:
        return bool(self.get("app", "debug_mode", default=False))

    @property
    def deployment_id(self) -> str:
        return str(self.get("app", "deployment_id", default="") or "")

    @property
    def manifest(self) -> dict[str, Any]:
        """``app.manifest`` sub-tree — runtime compatibility manifest config."""
        value = self.get("app", "manifest", default={}) or {}
        return value if isinstance(value, dict) else {}

    # ---- features ----------------------------------------------------------

    def feature(self, name: str) -> dict[str, Any]:
        value = self.get("features", name, default={})
        return value if isinstance(value, dict) else {}

    def feature_enabled(self, name: str) -> bool:
        return bool(self.feature(name).get("enabled", False))

    def enabled_features(self) -> list[str]:
        features = self.get("features", default={}) or {}
        return [name for name, cfg in features.items() if isinstance(cfg, dict) and cfg.get("enabled")]

    # ---- notifications -----------------------------------------------------

    @property
    def slack_enabled(self) -> bool:
        return bool(self.get("notifications", "slack", "enabled", default=False))

    @property
    def slack_webhook_env(self) -> str:
        return str(self.get("notifications", "slack", "webhook_url_env", default="SLACK_WEBHOOK_URL"))

    @property
    def slack_default_channel(self) -> str | None:
        return self.get("notifications", "slack", "default_channel")

    @property
    def email_enabled(self) -> bool:
        return bool(self.get("notifications", "email", "enabled", default=False))

    @property
    def email_provider(self) -> str:
        return str(self.get("notifications", "email", "provider", default="stdout"))

    @property
    def email_from_address(self) -> str:
        return str(self.get("notifications", "email", "from_address", default="alerts@example.com"))

    # ---- routing -----------------------------------------------------------

    @property
    def default_route(self) -> str:
        return str(self.get("routing", "default_route", default="finops"))

    def route(self, route_key: str) -> dict[str, Any]:
        value = self.get("routing", "routes", route_key, default={})
        return value if isinstance(value, dict) else {}

    # ---- delivery ----------------------------------------------------------

    @property
    def delivery(self) -> dict[str, Any]:
        value = self.get("delivery", default={})
        return value if isinstance(value, dict) else {}

    # ---- state -------------------------------------------------------------

    @property
    def state_backend(self) -> str:
        return str(self.get("state", "backend", default="memory")).lower()

    @property
    def state_file_path(self) -> str:
        return str(self.get("state", "file_path", default="/tmp/cloud-alert-hub-dedupe.json"))

    # GCS / S3 (object_path also reused by file-on-disk for the cloud backends)
    @property
    def state_bucket(self) -> str:
        return str(self.get("state", "bucket", default="") or "")

    @property
    def state_object_path(self) -> str:
        return str(self.get("state", "object_path", default="dedup-state.json"))

    # S3 only
    @property
    def state_region(self) -> str | None:
        value = self.get("state", "region", default=None)
        return str(value) if value else None

    # Azure Blob Storage
    @property
    def state_account_name(self) -> str:
        return str(self.get("state", "account_name", default="") or "")

    @property
    def state_container(self) -> str:
        return str(self.get("state", "container", default="") or "")

    @property
    def state_blob_name(self) -> str:
        return str(self.get("state", "blob_name", default="dedup-state.json"))

    @property
    def state_connection_string_env(self) -> str | None:
        value = self.get("state", "connection_string_env", default=None)
        return str(value) if value else None

    # ---- payload overrides -------------------------------------------------

    @property
    def payload_overrides_enabled(self) -> bool:
        return bool(self.get("payload_overrides", "enabled", default=True))

    @property
    def payload_override_keys(self) -> set[str]:
        keys = self.get("payload_overrides", "allowed_keys", default=[]) or []
        return {str(k) for k in keys}

    # ---- ingress auth (local-dev server) -----------------------------------

    @property
    def ingress_auth_enabled(self) -> bool:
        return bool(self.get("ingress_auth", "enabled", default=False))

    @property
    def ingress_auth_token_env(self) -> str:
        return str(self.get("ingress_auth", "shared_token_env", default="INGEST_SHARED_TOKEN"))


def load_config(user_config: Any = None) -> Config:
    """Build a :class:`Config` from bundled defaults + user overrides + env vars.

    Args:
        user_config: one of
            - ``None`` (use bundled defaults only)
            - a ``dict`` of overrides
            - a filesystem path (``str`` or :class:`pathlib.Path`) to a YAML file
            - a raw YAML string
    """
    merged = _deep_merge(_load_bundled_defaults(), _coerce_user_config(user_config))
    merged = _apply_env_overrides(merged)
    return Config(merged)
