import copy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import autobard.calibration_ui as ui
from autobard.calibration import prepare_calibration, save_calibration
from autobard.config import load_config
from autobard.models import Rect


def test_letterboxed_selection_maps_to_original_image_and_clamps():
    v = ui.ImageViewport.fit(2560, 1440, 1920, 1080)
    sx, sy = v.width / 2560, v.height / 1440
    rect = v.selection((v.left + 800 * sx, v.top + 900 * sy),
                       (v.left + 1200 * sx, v.top + 1000 * sy))
    assert rect == Rect(800, 900, 1200, 1000)
    assert v.selection((-100, -100), (9999, 9999)) == Rect(0, 0, 2560, 1440)
    assert v.selection((v.left, v.top), (v.left + 0.1, v.top + 0.1)) is None


def test_reverse_drag_and_zoomed_second_step_map_correctly():
    v = ui.ImageViewport.fit(574, 124, 2560, 1440)
    sx, sy = v.width / 574, v.height / 124
    result = v.selection((v.left + 550 * sx, v.top + 70 * sy),
                         (v.left + 10 * sx, v.top + 53 * sy))
    assert result == Rect(10, 53, 550, 70)
    assert not v.contains(20, 30)  # The guide heading is not part of the image.


def candidate_scene(tmp_path):
    cfg = load_config(tmp_path / "absent.json")
    cfg["vision"]["notes"].update(min_brightness_p90=0)
    image = np.full((160, 600, 3), 20, dtype=np.uint8)
    for x in [150, 250, 350, 450]:
        cv2.rectangle(image, (x - 10, 75), (x + 10, 92), (30, 190, 245), -1)
    return cfg, image


def test_candidate_does_not_mutate_settings_or_write_until_confirmed(tmp_path):
    cfg, image = candidate_scene(tmp_path)
    original = copy.deepcopy(cfg)
    # The parent lives on a monitor with a negative origin; stored coordinates
    # must still be relative to the client image, not the desktop or UI header.
    candidate = prepare_calibration(cfg, Rect(-600, 200, 0, 360), image,
                                    Rect(100, 60, 500, 110), Rect(0, 15, 400, 33))
    assert candidate.note_count == 4
    assert cfg == original
    assert not (tmp_path / "settings.json").exists()
    assert candidate.config["capture"]["roi_normalized"] == [100 / 600, 60 / 160, 500 / 600, 110 / 160]
    save_calibration(candidate, tmp_path / "settings.json")
    assert load_config(tmp_path / "settings.json")["vision"]["note_band_normalized"] == [0, 0.3, 1, 0.66]


def test_wrong_size_and_blank_region_never_produce_saved_calibration(tmp_path):
    cfg, image = candidate_scene(tmp_path)
    with pytest.raises(ValueError, match="截图尺寸"):
        prepare_calibration(cfg, Rect(0, 0, 500, 160), image, Rect(1, 1, 100, 100), Rect(0, 0, 90, 10))
    with pytest.raises(ValueError, match="没有识别到音符"):
        prepare_calibration(cfg, Rect(0, 0, 600, 160), image, Rect(0, 0, 100, 100), Rect(0, 0, 90, 10))
    assert not (tmp_path / "settings.json").exists()


@pytest.fixture
def wizard(monkeypatch, tmp_path):
    class Root:
        def __init__(self):
            self.jobs = {}
            self.sequence = 0

        def after(self, delay, callback):
            self.sequence += 1
            self.jobs[self.sequence] = (delay, callback)
            return self.sequence

        def after_cancel(self, token):
            self.jobs.pop(token, None)

    class Hint:
        def __init__(self, root):
            self.visible = False

        def show(self, *args):
            self.visible = True

        def hide(self):
            self.visible = False

        def destroy(self):
            self.visible = False

    class Listener:
        stopped = False

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(ui, "CalibrationHint", Hint)
    monkeypatch.setattr(ui.keyboard, "Listener", Listener)
    monkeypatch.setattr(ui, "primary_monitor_rect", lambda *args: Rect(0, 0, 600, 160))
    root = Root()
    output = []
    obj = ui.CalibrationWizard(root, load_config(tmp_path / "absent.json"),
                               tmp_path / "settings.json", lambda *args: output.append(args))
    yield obj, root, output
    if not obj.closed:
        obj.finish("calibration_cancelled", None)


def test_wrong_foreground_does_not_capture_or_start_timer(wizard, monkeypatch):
    obj, root, output = wizard
    monkeypatch.setattr(ui, "foreground_game_rect", lambda *args: None)
    monkeypatch.setattr(ui, "_grab", lambda *args: pytest.fail("Captured the wrong window"))
    obj.capture_event.set()
    obj.poll()
    assert obj.phase == "waiting"
    assert obj.deadline is None
    assert not obj.capture_event.is_set()
    assert obj.hint.visible


def test_countdown_hides_hint_then_rechecks_foreground_before_capture(wizard, monkeypatch):
    obj, root, output = wizard
    game = Rect(0, 0, 600, 160)
    obj.config["calibration"]["countdown_s"] = 0
    monkeypatch.setattr(ui, "foreground_game_rect", lambda *args: game)
    obj.poll()
    assert obj.phase == "hiding"
    assert not obj.hint.visible
    assert any(delay == 180 for delay, callback in root.jobs.values())
    # Switching away during compositor refresh must invalidate the capture.
    monkeypatch.setattr(ui, "foreground_game_rect", lambda *args: None)
    monkeypatch.setattr(ui, "_grab", lambda *args: pytest.fail("Captured after switch away"))
    obj.capture()
    assert obj.phase == "waiting"


def test_escape_cleans_timers_listener_and_preserves_file(wizard):
    obj, root, output = wizard
    obj.schedule(100, lambda: None)
    obj.cancel_event.set()
    obj.poll()
    assert obj.closed and obj.listener.stopped
    assert not root.jobs
    assert output == [("calibration_cancelled", None)]
    assert not obj.output_path.exists()
