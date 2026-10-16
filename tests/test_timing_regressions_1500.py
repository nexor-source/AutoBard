"""Replay observed trajectories; this does not claim counterfactual game grades."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import autobard.runtime as runtime
from autobard.config import _package_defaults
from autobard.models import CaptureFrame, Note, PointerMeasurement, Rect
from autobard.tracking import PointerTracker

FIXTURES = Path(__file__).parent / "fixtures" / "20261016"


@pytest.mark.parametrize("case", ["early_fast", "early_slow", "stalled_frame"])
def test_session_timing_follows_observations_instead_of_unreliable_model(monkeypatch, tmp_path, case):
    trace = json.loads((FIXTURES / f"{case}_trace.json").read_text())
    cfg = _package_defaults()
    cfg["scheduler"]["initial_skip_notes"] = 0
    cfg["scheduler"]["require_gold_window"] = True
    cfg["session"].update(initial_note_frames=1, initial_frame_spacing_ms=0,
                          post_complete_observe_ms=0)
    cfg["debug"].update(enabled=True, output_dir=str(tmp_path))

    class Source:
        index = -1
        timestamp = trace["rows"][0]["t"] - 0.02
        x = 6.0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            if self.index >= 0:
                row = trace["rows"][self.index]
                self.timestamp, self.x = row["t"], row["x"]
            self.index += 1
            image = np.full((124, 574, 3), 80, np.uint8)
            if self.x is not None:
                image[:, int(round(self.x))] = (40, 215, 250)
            return CaptureFrame(image, self.timestamp)

    class Notes:
        def __init__(self, *_args):
            pass

        def detect(self, *_args):
            return SimpleNamespace(notes=[Note(i, x - 6, x + 6, x, 1)
                                          for i, x in enumerate(trace["targets"])],
                                   mask=np.zeros((31, 574), np.uint8))

    class Pointer:
        def __init__(self, *_args):
            pass

        def detect(self, *_args, **_kwargs):
            return PointerMeasurement(source.x, 1.0, 4) if source.x is not None else None

    class Action:
        positions = []

        def hit_note(self, note, _timestamp):
            # The same input latency is used in old and new scheduling policies.
            if note.index == 1:
                assert source.x is not None
                self.positions.append(source.x - note.target)

    source = Source()
    monkeypatch.setattr(runtime, "create_capture", lambda *_args: source)
    monkeypatch.setattr(runtime, "NoteDetector", Notes)
    monkeypatch.setattr(runtime, "PointerDetector", Pointer)
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)
    action = Action()
    result = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), action).run()
    assert result.hit_count == (1 if case == "stalled_frame" else 2)
    rows = list(csv.DictReader(next(tmp_path.glob("*/tracking.csv")).open()))
    hits = [r for r in rows if r["events"].startswith("H")]
    assert all(abs(offset) <= 5 for offset in action.positions)
    if case == "stalled_frame":
        assert [r["events"] for r in hits] == ["H0"]
        assert result.missed_count == 1
        assert any(r["frame_is_fresh"] == "False" for r in rows)
        return
    assert [r["events"] for r in hits] == ["H0", "H1"]
    if case != "stalled_frame":
        assert hits[0]["speed_locked"] == "False"
        assert hits[1]["speed_locked"] == "True"
        assert 64 < float(hits[1]["speed"]) < 69
    assert hits[1]["schedule_mode"] == "live"


def test_high_r_squared_over_37ms_is_not_a_reliable_session_speed():
    trace = json.loads((FIXTURES / "early_fast_trace.json").read_text())
    tracker = PointerTracker(_package_defaults()["tracking"], 574)
    for row in trace["rows"][:4]:
        tracker.update(row["t"], PointerMeasurement(row["x"], 1, 4))
    assert tracker.last_fit.r_squared > 0.99
    assert tracker.speed > 80
    assert not tracker.try_lock_session_speed(trace["rows"][3]["t"])
    assert not tracker.has_locked_speed


def test_stale_frame_guard_allows_normal_duplicates_and_recovers_on_new_image():
    guard = runtime._FrameFreshnessGuard(80)
    image = np.zeros((10, 10, 3), np.uint8)
    assert guard.observe(1.0, image)
    assert guard.observe(1.016, image)
    assert not guard.observe(1.1, image)
    changed = image.copy()
    changed[0, 0] = 1
    assert guard.observe(1.11, changed)
