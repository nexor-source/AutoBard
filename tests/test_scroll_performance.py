"""Run the actual image detectors and session loop against a simulated game."""

import threading

import cv2
import numpy as np
import pytest

import autobard.runtime as runtime
from autobard.actions.base import ActionSink
from autobard.config import load_config, save_config
from autobard.models import CaptureFrame, Rect, SessionState


@pytest.mark.parametrize("skip", [0, 1])
@pytest.mark.parametrize("speed", [60, 180, 400])
def test_scroll_starts_game_then_plays_selected_notes(monkeypatch, tmp_path, skip, speed):
    cfg = load_config(tmp_path / "absent.json")
    cfg["action"].update(mode="system_input", kind="mouse_right")
    cfg["scheduler"]["initial_skip_notes"] = skip
    cfg["session"].update(max_duration_s=8, post_complete_observe_ms=0)
    cfg["debug"].update(enabled=True, output_dir=str(tmp_path / "debug"))
    events = []
    state = {"start": None, "offset": 0, "startup_clicks": 0}

    class Source:
        timestamp = 1000.0

        def __enter__(self):
            events.append("capture_open")
            return self

        def __exit__(self, *_args):
            events.append("capture_close")

        def read(self):
            self.timestamp += 1 / 70
            image = np.full((124, 574, 3), 20, dtype=np.uint8)
            if state["start"] is None:
                events.append("warmup")
                return CaptureFrame(image, self.timestamp)
            elapsed = self.timestamp - state["start"]
            # The game needs a few frames to display its performance bar.
            if elapsed >= 0.055:
                image[50:81, :] = (80, 80, 80)
                # The left-edge ornament is a known false note in real captures.
                cv2.rectangle(image, (2, 52), (28, 75), (25, 30, 220), -1)
                for index, x in enumerate((70, 260, 440)):
                    if index == 0 and state["startup_clicks"] == 2:
                        continue  # The game removes the note after the skip input.
                    cv2.rectangle(image, (x - 7, 52), (x + 7, 75), (30, 190, 245), -1)
                x = round(state["offset"] + elapsed * speed)
                cv2.line(image, (x, 5), (x, 118), (40, 215, 250), 2)
            return CaptureFrame(image, self.timestamp)

    source = Source()

    class Action(ActionSink):
        hits = []

        def start_performance(self, timestamp):
            events.append("startup_click")
            assert "warmup" in events
            state["startup_clicks"] += 1
            if state["start"] is None:
                state["start"] = source.timestamp
            else:
                state["offset"] = 100

        def hit_note(self, note, timestamp):
            self.hits.append(note.target)
            events.append(f"hit{note.index}")

    monkeypatch.setattr(runtime, "create_capture", lambda *_args: source)
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)
    original_save_image = runtime.DebugRecorder.save_image

    def save_image(recorder, name, image):
        if name == "initial_capture.png":
            events.append("initial_debug_saved")
        original_save_image(recorder, name, image)

    monkeypatch.setattr(runtime.DebugRecorder, "save_image", save_image)
    action = Action()
    result = runtime.AutoBardSession(
        cfg, Rect(0, 0, 574, 124), action, start_performance=True,
        can_start=lambda: True, on_started=lambda: events.append("takeover"),
    ).run()
    assert state["startup_clicks"] == 1 + skip
    targets = [70, 260, 440] if skip == 0 else [260, 440]
    assert len(action.hits) == len(targets)
    assert all(abs(hit - target) <= 2 for hit, target in zip(action.hits, targets))
    assert result.state == SessionState.FINISHED
    assert result.hit_count == 3 - skip
    assert events.index("takeover") > events.index("startup_click")
    assert events.index("initial_debug_saved") > events.index(f"hit{2 - skip}")
    assert events[-2:] == ["capture_close", "initial_debug_saved"]


@pytest.mark.parametrize("reason", ["abort", "focus"])
def test_cancel_between_startup_clicks_suppresses_second_input(tmp_path, reason):
    cfg = load_config(tmp_path / "absent.json")
    cfg["action"]["mode"] = "system_input"
    cfg["scheduler"]["initial_skip_notes"] = 1
    abort = threading.Event()
    focused = [True]
    clicks = []

    class Action:
        def start_performance(self, _timestamp):
            clicks.append("right")
            if reason == "abort":
                abort.set()
            else:
                focused[0] = False

    session = runtime.AutoBardSession(
        cfg, Rect(0, 0, 574, 124), start_performance=True,
        abort_event=abort, can_start=lambda: focused[0],
    )
    with pytest.raises(runtime._SessionInterrupted):
        session._begin_performance(Action())
    assert clicks == ["right"]


def test_dry_run_scroll_does_not_send_startup_input(tmp_path):
    cfg = load_config(tmp_path / "absent.json")

    class NoInput:
        def start_performance(self, _timestamp):
            pytest.fail("dry_run must not send input")

    session = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), start_performance=True)
    session._begin_performance(NoInput())


def test_cancel_before_start_never_opens_capture(monkeypatch, tmp_path):
    cfg = load_config(tmp_path / "absent.json")
    abort = threading.Event()
    abort.set()
    monkeypatch.setattr(runtime, "create_capture", lambda *a: pytest.fail("must not open capture"))
    result = runtime.AutoBardSession(
        cfg, Rect(0, 0, 574, 124), start_performance=True, abort_event=abort,
    ).run()
    assert result.state == SessionState.ABORTED


def test_scroll_choices_survive_saving_existing_configuration(tmp_path):
    path = tmp_path / "settings.json"
    cfg = load_config(path)
    original_roi = cfg["capture"]["roi_normalized"][:]
    cfg["hotkeys"]["trigger"] = "scroll_up"
    cfg["scheduler"]["initial_skip_notes"] = 0
    cfg["feedback"]["sound_enabled"] = False
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded["hotkeys"]["trigger"] == "scroll_up"
    assert loaded["scheduler"]["initial_skip_notes"] == 0
    assert loaded["feedback"]["sound_enabled"] is False
    assert loaded["capture"]["roi_normalized"] == original_roi


def test_note_snapshot_waits_for_skip_input_to_take_effect(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from autobard.models import Note

    cfg = load_config(tmp_path / "absent.json")

    class Source:
        timestamp = 1000.0

        def read(self):
            self.timestamp += 0.01
            return CaptureFrame(np.full((124, 574, 3), 80, np.uint8), self.timestamp)

    source = Source()

    class Notes:
        def __init__(self, *_args):
            pass

        def detect(self, _image, **_kwargs):
            # Until the startup click is processed the skipped note is still visible.
            centers = [70, 260, 440] if source.timestamp < 1000.045 else [260, 440]
            return SimpleNamespace(notes=[Note(i, x - 7, x + 7, x, 1)
                                          for i, x in enumerate(centers)])

    monkeypatch.setattr(runtime, "NoteDetector", Notes)
    from autobard.models import PointerMeasurement
    monkeypatch.setattr(runtime, "vertical_pointer_measurement", lambda *_: PointerMeasurement(6, 1, 3))
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)
    session = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), start_performance=True)
    session.performance_started_at = 1000.0
    session.startup_ready_at = 1000.045
    _, _, result = session._read_notes(source)
    assert [note.target for note in result.notes] == [260, 440]


def test_startup_preserves_real_notes_near_left_edge_and_filters_thin_strings():
    from autobard.models import Note

    notes = [Note(0, 2, 29, 15, 1), Note(1, 61, 75, 68, 1),
             Note(2, 132, 146, 138.5, 1), Note(3, 557, 570, 563, 1),
             Note(4, 380, 383, 381, 1)]
    assert runtime._startup_notes(notes) == notes[:4]


@pytest.mark.parametrize("key,value", [
    ("trigger", "both"), ("initial_skip_notes", 2), ("sound_enabled", "false"),
])
def test_invalid_scroll_settings_are_rejected_without_saving(tmp_path, key, value):
    from autobard.config import validate_config

    cfg = load_config(tmp_path / "absent.json")
    section = {"trigger": "hotkeys", "initial_skip_notes": "scheduler", "sound_enabled": "feedback"}[key]
    cfg[section][key] = value
    with pytest.raises(ValueError):
        validate_config(cfg)
