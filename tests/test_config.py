"""Config loading and env-override behaviour."""

from __future__ import annotations

from cloud_alert_hub.config import load_config


def test_bundled_defaults_load_without_user_input() -> None:
    cfg = load_config()
    assert cfg.default_route == "finops"
    assert cfg.state_backend == "memory"
    assert cfg.feature_enabled("budget_alerts") is False


def test_deep_merge_preserves_untouched_keys() -> None:
    user = {"app": {"environment": "qa"}, "features": {"budget_alerts": {"enabled": True}}}
    cfg = load_config(user)
    assert cfg.environment == "qa"
    assert cfg.feature_enabled("budget_alerts") is True
    assert cfg.feature_enabled("security_audit") is False
    assert cfg.default_route == "finops"


def test_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("DRY_RUN", "true")
    cfg = load_config({"app": {"environment": "qa", "dry_run": False}})
    assert cfg.environment == "prod"
    assert cfg.dry_run is True


def test_yaml_string_is_accepted() -> None:
    cfg = load_config(
        """
        app:
          environment: yaml-string
        routing:
          default_route: sre
        """
    )
    assert cfg.environment == "yaml-string"
    assert cfg.default_route == "sre"


def test_yaml_file_is_accepted(tmp_path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("app:\n  environment: from-file\n", encoding="utf-8")
    cfg = load_config(str(path))
    assert cfg.environment == "from-file"
