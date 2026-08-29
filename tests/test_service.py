from pynput import mouse

import autobard.service as service_module
from autobard.service import HotkeyService


def _config(interval_ms: int = 350) -> dict:
    return {
        "hotkeys": {
            "double_right_click_interval_ms": interval_ms,
            "abort": "<f9>",
            "quit": "<f10>",
        }
    }


def test_quick_double_right_click_starts_session(monkeypatch) -> None:
    timestamps = iter([1.0, 1.2])
    monkeypatch.setattr(service_module.time, "monotonic", lambda: next(timestamps))
    service = HotkeyService(_config())

    service._on_click(0, 0, mouse.Button.right, False)
    assert not service.start_event.is_set()
    service._on_click(0, 0, mouse.Button.right, False)

    assert service.start_event.is_set()


def test_slow_right_clicks_do_not_start_session(monkeypatch) -> None:
    timestamps = iter([1.0, 1.5])
    monkeypatch.setattr(service_module.time, "monotonic", lambda: next(timestamps))
    service = HotkeyService(_config())

    service._on_click(0, 0, mouse.Button.right, False)
    service._on_click(0, 0, mouse.Button.right, False)

    assert not service.start_event.is_set()


def test_public_service_controls_delegate_to_runtime() -> None:
    service = HotkeyService(_config())

    service.request_session()
    assert service.start_event.is_set()

    service.stop()
    assert service.quit_event.is_set()
