import csv

import cv2
import numpy as np

from autobard.debug import DebugRecorder


def test_debug_recorder_buffers_event_and_followup_frames(tmp_path) -> None:
    recorder = DebugRecorder(
        {
            "enabled": True,
            "output_dir": str(tmp_path),
            "event_follow_frames": 2,
        },
        (40, 20),
        60,
    )
    image = np.zeros((20, 40, 3), dtype=np.uint8)
    recorder.record(1, 1.0, image, 10.0, 1.0, 100.0, 1, events="H1")
    recorder.record(2, 1.02, image, 12.0, 1.0, 100.0, 1)
    recorder.record(3, 1.04, image, 14.0, 1.0, 100.0, 1)
    recorder.close()

    event_images = sorted(recorder.directory.glob("event_*.jpg"))
    assert len(event_images) == 3
    with (recorder.directory / "tracking.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["events"] == "H1"
    assert "action_submit_delay_ms" in rows[0]
    assert "action_call_ms" in rows[0]
    assert "candidate_x" in rows[0]
    assert "acquisition_state" in rows[0]
    assert "post_action_state" in rows[0]
    assert "post_action_outcome" in rows[0]


def test_raw_event_frame_is_lossless_and_not_the_overlay(tmp_path) -> None:
    recorder = DebugRecorder({"enabled": True, "output_dir": str(tmp_path),
                              "event_follow_frames": 0}, (40, 20), 60)
    raw = np.full((20, 40, 3), (7, 83, 201), dtype=np.uint8)
    overlay = np.zeros_like(raw)
    recorder.record(1, 1.0, overlay, 10.0, 1.0, 60.0, 1,
                    events="H1", raw_frame=raw)
    raw[:] = 0
    recorder.close()
    saved = cv2.imread(str(next(recorder.directory.glob("event_*_raw.png"))))
    assert np.all(saved == np.array([7, 83, 201], dtype=np.uint8))
