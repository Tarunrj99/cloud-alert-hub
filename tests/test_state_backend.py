from cloud_alert_hub.config import load_config
from cloud_alert_hub.state import FileState, InMemoryState, create_state_backend


def test_file_state_dedupe(tmp_path) -> None:
    state_file = tmp_path / "dedupe.json"
    state = FileState(str(state_file))
    key = "cloud:project:rule"

    first = state.should_suppress(key, window_seconds=600)
    second = state.should_suppress(key, window_seconds=600)

    assert first is False
    assert second is True


def test_create_state_backend_picks_memory_by_default() -> None:
    cfg = load_config()
    assert isinstance(create_state_backend(cfg), InMemoryState)


def test_create_state_backend_picks_file_when_configured(tmp_path) -> None:
    cfg = load_config({"state": {"backend": "file", "file_path": str(tmp_path / "s.json")}})
    assert isinstance(create_state_backend(cfg), FileState)
