"""Regressions from the user's 2026-10-16 14:27–14:30 game tests."""

from pathlib import Path

import cv2
import numpy as np
import pytest

import autobard.runtime as runtime
from autobard.config import _package_defaults
from autobard.models import CaptureFrame, Rect
from autobard.tracking import PointerBootstrapper
from autobard.vision.pointer import PointerDetector, vertical_pointer_measurement

FIXTURES = Path(__file__).parent / "fixtures" / "20261016"
BAND = [2 / 574, 53 / 124, 1.0, 70 / 124]


@pytest.mark.parametrize("name,targets", [
    ("left_note", [16, 93.5, 171, 249, 327, 405, 482.5, 560.5]),
    ("wide_rope", [131.5, 267, 402.5, 538]),
    ("crowded_wide", [262, 395, 461.5, 528]),
    ("cursor5", [66.5, 137.5, 208, 278.5, 349.5, 420, 490.5, 561.5]),
    ("free_chord", [97.5, 199.5, 250.5, 402.5, 504.5, 555.5]),
])
def test_startup_keeps_gold_notes_and_rejects_pointer_and_strings(monkeypatch, name, targets):
    cfg = _package_defaults()
    cfg["vision"]["note_band_normalized"] = BAND
    image = cv2.imread(str(FIXTURES / f"{name}.png"))

    class Source:
        timestamp = 1000.0

        def read(self):
            self.timestamp += 1 / 70
            return CaptureFrame(image, self.timestamp)

    source = Source()
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)
    session = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), start_performance=True)
    session.performance_started_at = 1000.0
    _, band, result = session._read_notes(source)
    actual = [note.target + band.left for note in result.notes]
    assert len(actual) == len(targets)
    assert max(abs(a - b) for a, b in zip(actual, targets)) <= 1.0


@pytest.mark.parametrize("name,expected", [
    ("left_note", 6.5), ("cursor5", 5.0), ("cursor18", 18.0),
    ("wide_rope", 60.5), ("crowded_wide", 33.5), ("healthy_hit", 117.0),
])
def test_actual_vertical_pointer_beats_animated_string_even_with_wrong_prediction(name, expected):
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    detector = PointerDetector(_package_defaults()["vision"]["pointer"], (BAND[1], BAND[3]))
    measurement = detector.detect(image, predicted_x=140)
    assert measurement is not None
    assert abs(measurement.x - expected) <= 2.0


def test_result_text_and_strings_cannot_start_a_performance(monkeypatch):
    image = cv2.imread(str(FIXTURES / "result.png"))
    assert vertical_pointer_measurement(image, (BAND[1], BAND[3])) is None
    cfg = _package_defaults()
    cfg["vision"]["note_band_normalized"] = BAND
    cfg["session"]["startup_note_timeout_ms"] = 100

    class Source:
        timestamp = 1000.0

        def read(self):
            self.timestamp += 0.02
            return CaptureFrame(image, self.timestamp)

    source = Source()
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)
    session = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), start_performance=True)
    session.performance_started_at = 1000.0
    with pytest.raises(RuntimeError, match="指针"):
        session._read_notes(source)


def test_stationary_pointer_with_moving_diagonal_strings_cannot_lock_false_speed():
    cfg = _package_defaults()
    detector = PointerDetector(cfg["vision"]["pointer"], (BAND[1], BAND[3]))
    bootstrap = PointerBootstrapper(cfg["tracking"], 574)
    for index in range(12):
        image = np.full((124, 574, 3), 25, dtype=np.uint8)
        x = 80 + index * 7
        cv2.line(image, (x - 40, 6), (x + 40, 118), (40, 205, 245), 2)
        cv2.line(image, (6, 4), (6, 119), (40, 215, 250), 2)
        measurement = detector.detect(image)
        assert measurement is not None and abs(measurement.x - 6) <= 1
        assert bootstrap.update(index / 70, measurement) is None


def test_failed_startup_preserves_frames_and_timing_without_sending_input(monkeypatch, tmp_path):
    import json

    image = cv2.imread(str(FIXTURES / "result.png"))
    cfg = _package_defaults()
    cfg["vision"]["note_band_normalized"] = BAND
    cfg["session"]["startup_note_timeout_ms"] = 100
    cfg["debug"].update(enabled=True, output_dir=str(tmp_path))
    closed = []

    class Source:
        timestamp = 1000.0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            closed.append(True)

        def read(self):
            self.timestamp += 0.02
            return CaptureFrame(image, self.timestamp)

    class NoInput:
        def hit_note(self, *_args):
            pytest.fail("result screen must not receive a note click")

    source = Source()
    monkeypatch.setattr(runtime, "create_capture", lambda *_: source)
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)
    with pytest.raises(RuntimeError, match="指针"):
        runtime.AutoBardSession(
            cfg, Rect(0, 0, 574, 124), NoInput(), start_performance=True,
        ).run()
    timing_file = next(tmp_path.glob("*/startup_frames.json"))
    timing = json.loads(timing_file.read_text(encoding="utf-8"))
    assert timing["startup_input_timestamps"] == []
    assert len(timing["frames"]) >= 2
    assert (timing_file.parent / timing["frames"][0]["image"]).is_file()
    assert (timing_file.parent / "startup_result.json").is_file()
    assert closed == [True]
