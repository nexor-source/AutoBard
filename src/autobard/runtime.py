from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .actions import create_action_sink
from .actions.base import ActionSink
from .capture import create_capture
from .debug import DebugRecorder
from .debug.overlay import draw_overlay
from .models import Note, PointerMeasurement, Rect, SessionState
from .timing import NoteScheduler
from .tracking import PointerTracker
from .vision import NoteDetector, PointerDetector

LOGGER = logging.getLogger(__name__)


def _capture_has_signal(bgr: np.ndarray) -> bool:
    """Reject only genuinely blank capture frames, not frames with changed notes."""
    if bgr.ndim != 3 or bgr.shape[2] < 3 or bgr.size == 0:
        return False
    # The captured rhythm bar contributes well over one percent bright pixels
    # even in the darkest collected samples. An intermittent MSS black frame
    # has no such signal. This deliberately does not depend on note color:
    # already-hit notes change color and narrow pending notes may occupy less
    # than ten percent of the note band.
    return float(np.percentile(bgr[:, :, :3], 99.0)) >= 32.0


@dataclass(slots=True)
class SessionResult:
    state: SessionState
    note_count: int
    hit_count: int
    missed_count: int
    frame_count: int
    average_fps: float


class AutoBardSession:
    def __init__(self, config: dict, capture_rect: Rect, action: ActionSink | None = None) -> None:
        self.config = config
        self.capture_rect = capture_rect
        self.action = action
        self.abort_event = threading.Event()

    def abort(self) -> None:
        self.abort_event.set()

    def _read_initial_frames(self, source) -> tuple[np.ndarray, float]:
        session_cfg = self.config["session"]
        count = max(1, int(session_cfg.get("initial_note_frames", 5)))
        spacing = max(0.0, float(session_cfg.get("initial_frame_spacing_ms", 8)) / 1000.0)
        images: list[np.ndarray] = []
        timestamp = 0.0
        for _ in range(count):
            captured = source.read()
            images.append(captured.image)
            timestamp = captured.timestamp
            if spacing:
                time.sleep(spacing)
        median = np.median(np.stack(images, axis=0), axis=0).astype(np.uint8)
        return median, timestamp

    def run(self) -> SessionResult:
        self.abort_event.clear()
        capture_cfg = self.config["capture"]
        vision_cfg = self.config["vision"]
        source = create_capture(
            str(capture_cfg.get("backend", "auto")),
            self.capture_rect,
            int(capture_cfg.get("target_fps", 120)),
        )
        action = self.action
        owns_action = action is None
        if action is None:
            action = create_action_sink(self.config["action"])
        start_wall = time.perf_counter()
        state = SessionState.READING_NOTES
        frame_count = 0
        recorder: DebugRecorder | None = None

        try:
            with source:
                initial, initial_timestamp = self._read_initial_frames(source)
                height, width = initial.shape[:2]
                note_band = Rect(0, 0, width, height).subrect_from_normalized(vision_cfg["note_band_normalized"])
                note_crop = note_band.crop(initial)
                note_detector = NoteDetector(vision_cfg["notes"])
                note_result = note_detector.detect(note_crop)
                notes: list[Note] = []
                for note in note_result.notes:
                    note.left += note_band.left
                    note.right += note_band.left
                    note.target += note_band.left
                    notes.append(note)
                if not notes:
                    raise RuntimeError("No notes detected. Run calibration/inspect-image and review debug output.")

                LOGGER.info("Detected %d notes at %s", len(notes), [round(note.target, 1) for note in notes])
                scheduler = NoteScheduler(notes, self.config["scheduler"], width)
                tracker = PointerTracker(self.config["tracking"], width)
                pointer_detector = PointerDetector(vision_cfg["pointer"])
                recorder = DebugRecorder(self.config["debug"], (width, height), int(capture_cfg["target_fps"]))
                recorder.save_image("initial_capture.jpg", initial)
                recorder.save_image("note_mask.png", note_result.mask)
                recorder.save_image("notes_overlay.jpg", draw_overlay(initial, notes, note_band))

                state = SessionState.TRACKING_POINTER
                first_timestamp = initial_timestamp
                last_valid_pointer_at: float | None = None
                prediction_hold_s = float(self.config["tracking"].get("prediction_hold_ms", 90)) / 1000.0
                lost_timeout_s = float(self.config["session"].get("pointer_lost_timeout_ms", 320)) / 1000.0
                minimum_runtime_s = float(self.config["session"].get("minimum_runtime_ms", 250)) / 1000.0
                max_duration_s = float(self.config["session"].get("max_duration_s", 8.0))
                completed_at: float | None = None
                post_complete_observe_s = max(
                    0.0,
                    float(self.config["session"].get("post_complete_observe_ms", 150)) / 1000.0,
                )

                while not self.abort_event.is_set():
                    captured = source.read()
                    frame_count += 1
                    elapsed = captured.timestamp - first_timestamp

                    capture_has_signal = _capture_has_signal(captured.image)

                    predicted = tracker.predict(captured.timestamp)
                    bootstrap_x = (
                        notes[0].right
                        if predicted is None and frame_count > 1
                        else None
                    )
                    measurement = (
                        pointer_detector.detect(
                            captured.image,
                            predicted,
                            bootstrap_x=bootstrap_x,
                        )
                        if capture_has_signal
                        else None
                    )
                    accepted = measurement is not None and tracker.update(captured.timestamp, measurement)

                    pointer_for_schedule: float | None = None
                    measured_x = measurement.x if accepted and measurement is not None else None
                    shown_measurement = measurement if accepted else None
                    schedule_uses_model = False
                    if accepted:
                        next_note = scheduler.next_pending_note
                        model_max_width = width * float(
                            self.config["scheduler"].get(
                                "model_schedule_max_note_width_ratio",
                                0.05,
                            )
                        )
                        # The empirically best behavior uses the smooth model
                        # only for narrow notes. Wide notes retain the live
                        # measurement and its larger visual tolerance.
                        schedule_uses_model = (
                            tracker.has_locked_speed
                            and next_note is not None
                            and next_note.right - next_note.left <= model_max_width
                        )
                        pointer_for_schedule = (
                            tracker.predict(captured.timestamp)
                            if schedule_uses_model
                            else tracker.last_x
                        )
                        last_valid_pointer_at = captured.timestamp
                    elif (
                        capture_has_signal
                        and last_valid_pointer_at is not None
                        and captured.timestamp - last_valid_pointer_at <= prediction_hold_s
                    ):
                        pointer_for_schedule = tracker.predict(captured.timestamp)
                        if pointer_for_schedule is not None:
                            shown_measurement = PointerMeasurement(pointer_for_schedule, tracker.last_confidence * 0.6, 1.0)

                    event_labels: list[str] = []
                    action_submit_delays: list[str] = []
                    action_call_durations: list[str] = []
                    if pointer_for_schedule is not None:
                        update = scheduler.update(
                            captured.timestamp,
                            pointer_for_schedule,
                            tracker.speed,
                            use_model=schedule_uses_model,
                        )
                        event_labels.extend(f"M{note.index}" for note in update.newly_missed)
                        for note in update.due:
                            action_started = time.perf_counter()
                            action.hit_note(note, action_started)
                            action_finished = time.perf_counter()
                            action_submit_delays.append(
                                f"{(action_started - captured.timestamp) * 1000.0:.3f}"
                            )
                            action_call_durations.append(
                                f"{(action_finished - action_started) * 1000.0:.3f}"
                            )
                            event_labels.append(f"H{note.index}")
                            # Anchor at the actual VIIPER submission time.
                            # Using the earlier capture timestamp made the
                            # next model segment 5-12 ms too early.
                            tracker.reanchor_after_hit(action_started, note.target)
                        if update.newly_missed:
                            LOGGER.debug(
                                "Missed notes: %s",
                                [note.index for note in update.newly_missed],
                            )

                    overlay = draw_overlay(captured.image, notes, note_band, shown_measurement, tracker.speed)
                    recorder.record(
                        frame_count,
                        captured.timestamp,
                        overlay,
                        pointer_for_schedule,
                        shown_measurement.confidence if shown_measurement else 0.0,
                        tracker.speed,
                        scheduler.pending_count,
                        measured_x=measured_x,
                        events=";".join(event_labels),
                        schedule_mode="model" if schedule_uses_model else "live",
                        action_submit_delay_ms=";".join(action_submit_delays),
                        action_call_ms=";".join(action_call_durations),
                    )

                    if scheduler.complete:
                        state = SessionState.FINISHED
                        if completed_at is None:
                            completed_at = captured.timestamp
                        if captured.timestamp - completed_at >= post_complete_observe_s:
                            break
                        continue
                    if elapsed >= max_duration_s:
                        LOGGER.warning("Session timed out after %.2fs", elapsed)
                        state = SessionState.FINISHED
                        break
                    if (
                        elapsed >= minimum_runtime_s
                        and last_valid_pointer_at is not None
                        and captured.timestamp - last_valid_pointer_at >= lost_timeout_s
                    ):
                        LOGGER.info("Pointer lost for %.0fms; ending session", lost_timeout_s * 1000)
                        state = SessionState.FINISHED
                        break

                if self.abort_event.is_set():
                    state = SessionState.ABORTED

                duration = max(time.perf_counter() - start_wall, 1e-6)
                return SessionResult(
                    state=state,
                    note_count=len(notes),
                    hit_count=sum(note.status == "hit" for note in notes),
                    missed_count=sum(note.status == "missed" for note in notes),
                    frame_count=frame_count,
                    average_fps=frame_count / duration,
                )
        finally:
            if recorder is not None:
                recorder.close()
            if owns_action:
                action.close()
