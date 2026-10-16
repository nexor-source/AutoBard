from pynput import mouse
import pytest

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


@pytest.mark.parametrize("trigger,dy,starts", [
    ("scroll_up", 1, True), ("scroll_up", -1, False),
    ("scroll_down", -1, True), ("scroll_down", 1, False),
    ("scroll_down", 0, False), ("double_right_click", -1, False),
])
def test_scroll_only_accepts_selected_direction(monkeypatch, trigger, dy, starts):
    cfg = _config()
    cfg["hotkeys"]["trigger"] = trigger
    service = HotkeyService(cfg)
    monkeypatch.setattr(service, "_game_is_foreground", lambda: True)
    service._on_scroll(0, 0, 0, dy)
    assert service.start_event.is_set() == starts
    assert service._start_performance == starts


def test_scroll_outside_game_does_not_request_or_send_input(monkeypatch):
    cfg = _config()
    cfg["hotkeys"]["trigger"] = "scroll_down"
    service = HotkeyService(cfg)
    monkeypatch.setattr(service, "_game_is_foreground", lambda: False)
    service._on_scroll(0, 0, 0, -1)
    assert not service.start_event.is_set()
    assert not service._busy


def test_scroll_mode_ignores_right_clicks_including_its_own_input():
    cfg = _config()
    cfg["hotkeys"]["trigger"] = "scroll_down"
    service = HotkeyService(cfg)
    service._on_click(0, 0, mouse.Button.right, False)
    service._on_click(0, 0, mouse.Button.right, False)
    assert not service.start_event.is_set()


def test_scroll_burst_is_not_queued_again_after_finish(monkeypatch):
    cfg = _config()
    cfg["hotkeys"]["trigger"] = "scroll_down"
    service = HotkeyService(cfg)
    now = [1.0]
    monkeypatch.setattr(service_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(service, "_game_is_foreground", lambda: True)
    service._on_scroll(0, 0, 0, -1)
    assert service.start_event.is_set()
    service.start_event.clear()
    now[0] = 1.1
    service._on_scroll(0, 0, 0, -1)
    assert not service.start_event.is_set()
    service._busy = False
    service._finished_at = 1.1
    now[0] = 1.2
    service._on_scroll(0, 0, 0, -1)
    assert not service.start_event.is_set()
    now[0] = 1.8
    service._on_scroll(0, 0, 0, -1)
    assert service.start_event.is_set()


def test_abort_cancels_pending_start_before_worker_launch():
    service = HotkeyService(_config())
    service._start(start_performance=True)
    service.abort_session()
    assert not service.start_event.is_set()
    assert service._session_abort.is_set()
    assert not service._busy


@pytest.mark.parametrize("failed", [False, True])
def test_session_notifies_takeover_then_end_even_on_failure(monkeypatch, failed):
    from types import SimpleNamespace
    from autobard.models import Rect, SessionState

    service = HotkeyService(_config())
    service._start(start_performance=True)
    cues = []
    service.sounds = SimpleNamespace(play=cues.append)
    monkeypatch.setattr(service, "_game_is_foreground", lambda: True)
    monkeypatch.setattr(service_module, "resolve_capture_rect", lambda _: (None, Rect(0, 0, 100, 30)))

    class Session:
        def __init__(self, *args, **kwargs):
            assert kwargs["start_performance"]
            assert kwargs["abort_event"] is service._session_abort
            self.on_started = kwargs["on_started"]

        def run(self):
            self.on_started()
            if failed:
                raise RuntimeError("synthetic capture failure")
            return SimpleNamespace(state=SessionState.FINISHED, note_count=3, hit_count=3,
                                   missed_count=0, frame_count=40, average_fps=70)

    monkeypatch.setattr(service_module, "AutoBardSession", Session)
    service._run_session()
    assert cues == ["takeover", "end"]
    assert not service._busy


def test_focus_lost_after_scroll_prevents_session_launch(monkeypatch):
    service = HotkeyService(_config())
    service._start(start_performance=True)
    monkeypatch.setattr(service, "_game_is_foreground", lambda: False)
    monkeypatch.setattr(service_module, "AutoBardSession", lambda *a, **kw: pytest.fail("must not start"))
    service._run_session()
    assert not service._busy


@pytest.mark.parametrize("trigger,delta,focused,suppressed", [
    ("scroll_down", -120, True, True),
    ("scroll_up", 120, True, True),
    ("scroll_down", -15, True, True),
    ("scroll_down", 120, True, False),
    ("scroll_down", -120, False, False),
    ("double_right_click", -120, True, False),
])
def test_native_wheel_filter_swallows_only_chosen_direction_in_game(
    monkeypatch, trigger, delta, focused, suppressed,
):
    from types import SimpleNamespace
    from pynput._util.win32 import SystemHook

    cfg = _config()
    cfg["hotkeys"]["trigger"] = trigger
    service = HotkeyService(cfg)
    # suppress_event itself just raises the native hook's suppression exception;
    # no OS hook or input is created by this test.
    service._mouse_listener = object.__new__(mouse.Listener)
    monkeypatch.setattr(service, "_game_is_foreground", lambda: focused)
    data = SimpleNamespace(mouseData=(delta & 0xFFFF) << 16, pt=SimpleNamespace(x=10, y=20))
    if suppressed:
        with pytest.raises(SystemHook.SuppressException):
            service._filter_mouse_event(0x020A, data)
        assert service.start_event.is_set()
        service.start_event.clear()
        # Repeated wheel input during takeover is swallowed too, without queueing.
        with pytest.raises(SystemHook.SuppressException):
            service._filter_mouse_event(0x020A, data)
        assert not service.start_event.is_set()
    else:
        assert service._filter_mouse_event(0x020A, data) is True
        assert not service.start_event.is_set()
    # Ordinary buttons and horizontal wheel always pass through.
    assert service._filter_mouse_event(0x0204, data) is True
    assert service._filter_mouse_event(0x020E, data) is True
    service.quit_event.set()
    assert service._filter_mouse_event(0x020A, data) is True
