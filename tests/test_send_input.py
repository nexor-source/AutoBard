from autobard.actions import send_input
from autobard.models import Note


class ImmediateTimer:
    def __init__(self, _duration, callback) -> None:
        self.callback = callback
        self.daemon = False

    def start(self) -> None:
        self.callback()


def test_mouse_right_sends_down_and_up(monkeypatch) -> None:
    events: list[int] = []
    monkeypatch.setattr(send_input, "_mouse", events.append)
    monkeypatch.setattr(send_input.threading, "Timer", ImmediateTimer)
    action = send_input.SendInputAction("mouse_right", "space", 35)

    action.hit_note(Note(0, 10, 20, 15, 1.0), 1.25)

    assert events == [send_input.MOUSEEVENTF_RIGHTDOWN, send_input.MOUSEEVENTF_RIGHTUP]


def test_legacy_mouse_event_matches_old_down_hold_up(monkeypatch) -> None:
    events: list[int] = []
    sleeps: list[float] = []
    monkeypatch.setattr(send_input, "_legacy_mouse_event", events.append)
    monkeypatch.setattr(send_input.time, "sleep", sleeps.append)
    action = send_input.SendInputAction("mouse_right", "space", 10, "mouse_event")

    action.hit_note(Note(0, 10, 20, 15, 1.0), 1.25)

    assert events == [send_input.MOUSEEVENTF_RIGHTDOWN, send_input.MOUSEEVENTF_RIGHTUP]
    assert sleeps == [0.01]
