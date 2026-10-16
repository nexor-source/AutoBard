from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from collections.abc import Callable

import cv2
import numpy as np

from .actions import create_action_sink
from .actions.base import ActionSink
from .capture import create_capture
from .debug import DebugRecorder
from .debug.overlay import draw_overlay
from .models import Note, PointerMeasurement, Rect, SessionState
from .timing import NoteScheduler
from .tracking import (
    PointerBootstrapper,
    PointerTracker,
    PostActionTrajectoryVerifier,
)
from .vision import NoteDetector, PointerDetector
from .vision.pointer import vertical_pointer_measurement

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


def _remaining_pointer_start_delay_s(
    session_started_at: float,
    delay_ms: int,
    now: float,
) -> float:
    configured_s = max(0.0, float(delay_ms) / 1000.0)
    return max(0.0, configured_s - max(0.0, now - session_started_at))


def _startup_notes(notes: list[Note]) -> list[Note]:
    """Reject narrow strings by width, without excluding any screen position."""
    if len(notes) < 3:
        return notes
    typical_width = float(np.median([note.right - note.left for note in notes]))
    return [
        note for note in notes
        if note.right - note.left >= typical_width * 0.5
    ]


def _pointer_bootstrap_search_bounds(
    notes: list[Note],
    frame_width: int,
    elapsed_s: float,
    expand_ms: int,
    include_leading: bool = False,
) -> tuple[float, float]:
    """Expand startup search from the first two notes to the complete note lane."""
    ordered = sorted(notes, key=lambda note: note.target)
    margin = max(8.0, frame_width * 0.025)
    left = 0.0 if include_leading else max(0.0, ordered[0].left - margin)
    initial_right = min(
        float(frame_width - 1),
        ordered[min(1, len(ordered) - 1)].right + margin,
    )
    full_right = min(float(frame_width - 1), ordered[-1].right + margin)
    expand_s = max(0.0, float(expand_ms) / 1000.0)
    progress = 1.0 if expand_s == 0.0 else min(1.0, max(0.0, elapsed_s) / expand_s)
    right = initial_right + (full_right - initial_right) * progress
    return left, max(left + 1.0, right)


@dataclass(slots=True)
class SessionResult:
    state: SessionState
    note_count: int
    hit_count: int
    missed_count: int
    frame_count: int
    average_fps: float


class _SessionInterrupted(Exception):
    """Startup was cancelled before a usable performance could be acquired."""


class _FrameFreshnessGuard:
    def __init__(self, timeout_ms: float) -> None:
        self.timeout_s = max(0.02, timeout_ms / 1000)
        self.previous: np.ndarray | None = None
        self.last_change_at: float | None = None

    def observe(self, timestamp: float, image: np.ndarray) -> bool:
        if self.previous is None or not np.array_equal(self.previous, image):
            self.previous = image.copy()
            self.last_change_at = timestamp
        return timestamp - self.last_change_at <= self.timeout_s


class AutoBardSession:
    def __init__(
        self, config: dict, capture_rect: Rect, action: ActionSink | None = None,
        *, start_performance: bool = False, abort_event: threading.Event | None = None,
        can_start: Callable[[], bool] | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.capture_rect = capture_rect
        self.action = action
        self.abort_event = abort_event if abort_event is not None else threading.Event()
        self.start_performance = start_performance
        self.can_start = can_start
        self.on_started = on_started
        self.performance_started_at: float | None = None
        self.startup_ready_at = 0.0
        self.startup_input_timestamps: list[float] = []
        self.capture_ready_at: float | None = None
        self._startup_frames: list[tuple[float, np.ndarray]] = []

    def _remember_startup_frame(self, captured) -> None:
        if (
            self.start_performance and self.config.get("debug", {}).get("enabled", False)
            and len(self._startup_frames) < 60
        ):
            self._startup_frames.append((captured.timestamp, captured.image.copy()))

    def abort(self) -> None:
        self.abort_event.set()

    def _check_start_allowed(self) -> None:
        if self.abort_event.is_set() or (self.can_start is not None and not self.can_start()):
            raise _SessionInterrupted()

    def _begin_performance(self, action: ActionSink) -> None:
        self._check_start_allowed()
        count = 2 if self.config["scheduler"].get("initial_skip_notes", 1) else 1
        mode = str(self.config["action"].get("mode", "dry_run"))
        self.performance_started_at = time.perf_counter()
        self.startup_ready_at = self.performance_started_at
        if mode != "system_input":
            LOGGER.info("%s 模式：模拟启动 %d 次右键，不发送输入", mode, count)
            return
        if self.config["action"].get("kind", "mouse_right") != "mouse_right":
            raise ValueError("滚轮开始演奏需要 action.kind=mouse_right")
        interval_s = float(self.config["session"].get("startup_click_interval_ms", 100)) / 1000
        for index in range(count):
            if index and self.abort_event.wait(interval_s):
                raise _SessionInterrupted()
            self._check_start_allowed()
            submitted_at = time.perf_counter()
            action.start_performance(submitted_at)
            self.startup_input_timestamps.append(submitted_at)
            self.startup_ready_at = submitted_at + max(
                0.0, float(self.config["scheduler"].get("input_latency_ms", 45)) / 1000,
            )
        LOGGER.info("滚轮开始演奏：已发送 %d 次右键，跳过首音=%s", count, count == 2)

    def _read_notes(self, source):
        """Poll for the bar after startup without paying the legacy median delay."""
        vision_cfg = self.config["vision"]
        detector = NoteDetector(vision_cfg["notes"])
        timeout_s = float(self.config["session"].get("startup_note_timeout_ms", 2000)) / 1000
        deadline = time.perf_counter() + timeout_s
        previous_targets: list[float] | None = None
        while True:
            self._check_start_allowed()
            if self.start_performance:
                captured = source.read()
                self._remember_startup_frame(captured)
                initial = captured.image
                # DXcam can initially return the warmup frame, captured before input.
                if (
                    captured.timestamp <= self.performance_started_at
                    or captured.timestamp < self.startup_ready_at
                ):
                    if time.perf_counter() >= deadline:
                        raise RuntimeError("启动后未收到新的游戏画面，请检查截图后端。")
                    self.abort_event.wait(0.005)
                    continue
            else:
                initial, _ = self._read_initial_frames(source)
            height, width = initial.shape[:2]
            band = Rect(0, 0, width, height).subrect_from_normalized(vision_cfg["note_band_normalized"])
            note_crop = band.crop(initial)
            if self.start_performance:
                pointer = vertical_pointer_measurement(
                    initial,
                    (float(vision_cfg["note_band_normalized"][1]),
                     float(vision_cfg["note_band_normalized"][3])),
                )
                if pointer is None:
                    previous_targets = None
                    if time.perf_counter() >= deadline:
                        raise RuntimeError("未找到演奏指针；当前可能是结果画面，请检查调试截图。")
                    self.abort_event.wait(0.005)
                    continue
                note_crop = note_crop.copy()
                background = np.median(note_crop.reshape(-1, 3), axis=0).astype(np.uint8)
                hsv = cv2.cvtColor(note_crop, cv2.COLOR_BGR2HSV)
                # Red miss flashes and the long pointer are not pending notes.
                note_crop[(hsv[:, :, 0] < 10) & (hsv[:, :, 1] > 80)] = background
                left = max(0, int(np.floor(pointer.x - pointer.width / 2 - 1)) - band.left)
                right = min(note_crop.shape[1], int(np.ceil(pointer.x + pointer.width / 2 + 1)) - band.left)
                if right > left:
                    note_crop[:, left:right] = background
            if self.start_performance:
                result = detector.detect(note_crop, strict_gold=True)
            else:
                result = detector.detect(note_crop)
            if self.start_performance:
                result.notes = _startup_notes(result.notes)
            if result.notes:
                targets = [note.target for note in result.notes]
                if not self.start_performance or (
                    previous_targets is not None
                    and len(targets) == len(previous_targets)
                    and all(abs(a - b) <= 2.0 for a, b in zip(targets, previous_targets))
                ):
                    return initial, band, result
                previous_targets = targets
            else:
                previous_targets = None
            if not self.start_performance or time.perf_counter() >= deadline:
                raise RuntimeError("No notes detected. Run calibration/inspect-image and review debug output.")
            if self.abort_event.wait(0.005):
                raise _SessionInterrupted()

    def _read_initial_frames(self, source) -> tuple[np.ndarray, float]:
        session_cfg = self.config["session"]
        count = max(1, int(session_cfg.get("initial_note_frames", 5)))
        spacing = max(0.0, float(session_cfg.get("initial_frame_spacing_ms", 8)) / 1000.0)
        images: list[np.ndarray] = []
        timestamp = 0.0
        for _ in range(count):
            self._check_start_allowed()
            captured = source.read()
            images.append(captured.image)
            timestamp = captured.timestamp
            if spacing:
                if self.abort_event.wait(spacing):
                    raise _SessionInterrupted()
        median = np.median(np.stack(images, axis=0), axis=0).astype(np.uint8)
        return median, timestamp

    def run(self) -> SessionResult:
        if self.abort_event.is_set():
            return SessionResult(SessionState.ABORTED, 0, 0, 0, 0, 0.0)
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
        pending_initial_debug = None

        try:
            with source:
                if self.start_performance:
                    warmup = source.read()  # Prepare capture before the game starts moving.
                    self._remember_startup_frame(warmup)
                    self.capture_ready_at = time.perf_counter()
                    self._begin_performance(action)
                    start_wall = self.performance_started_at
                if self.on_started is not None:
                    self.on_started()
                initial, note_band, note_result = self._read_notes(source)
                height, width = initial.shape[:2]
                notes: list[Note] = []
                for note in note_result.notes:
                    note.left += note_band.left
                    note.right += note_band.left
                    note.target += note_band.left
                    notes.append(note)
                for index, note in enumerate(notes):
                    note.index = index
                if not notes:
                    raise RuntimeError("No notes detected. Run calibration/inspect-image and review debug output.")

                LOGGER.info("Detected %d notes at %s", len(notes), [round(note.target, 1) for note in notes])
                scheduler_cfg = dict(self.config["scheduler"])
                if self.start_performance:
                    # The second startup click already skipped a note in game.
                    # Schedule only the notes still present; never skip another.
                    scheduler_cfg["initial_skip_notes"] = 0
                    scheduler_cfg["require_gold_window"] = True
                scheduler = NoteScheduler(notes, scheduler_cfg, width)
                tracker = PointerTracker(self.config["tracking"], width)
                bootstrapper = PointerBootstrapper(self.config["tracking"], width)
                pointer_detector = PointerDetector(
                    vision_cfg["pointer"],
                    (float(vision_cfg["note_band_normalized"][1]),
                     float(vision_cfg["note_band_normalized"][3])),
                )
                if self.start_performance:
                    pointer_detector.detect(initial)
                recorder = DebugRecorder(self.config["debug"], (width, height), int(capture_cfg["target_fps"]))
                def save_initial_debug():
                    recorder.save_image("initial_capture.png", initial)
                    recorder.save_image("initial_capture.jpg", initial)
                    recorder.save_image("note_mask.png", note_result.mask)
                    recorder.save_image("notes_overlay.jpg", draw_overlay(initial, notes, note_band))
                    recorder.save_json(
                        "session_meta.json",
                        {
                            "pointer_start_delay_ms": int(
                                self.config["session"].get("pointer_start_delay_ms", 0)
                            ),
                            "bootstrap_confirm_frames": bootstrapper.confirm_frames,
                            "bootstrap_min_displacement": bootstrapper.min_displacement,
                            "bootstrap_min_r_squared": bootstrapper.min_r_squared,
                            "bootstrap_expand_ms": int(
                                self.config["tracking"].get("bootstrap_expand_ms", 150)
                            ),
                            "post_action_reanchor_samples": int(
                                self.config["tracking"].get("post_action_reanchor_samples", 3)
                            ),
                            "early_trigger_tolerance": scheduler.early_trigger_tolerance,
                            "frame_width": width,
                            "frame_height": height,
                            "pointer_detector": "calibrated_vertical_v1",
                            "startup_note_detector": "gold_core_v1" if self.start_performance else "adaptive_warm",
                            "startup_right_click_count": (
                                1 + int(bool(self.config["scheduler"].get("initial_skip_notes", 1)))
                                if self.start_performance
                                and self.config["action"].get("mode") == "system_input" else 0
                            ),
                            "scheduler_initial_skip_notes": scheduler.initial_skip_notes,
                            "capture_ready_at": self.capture_ready_at,
                            "startup_input_timestamps": self.startup_input_timestamps,
                            "config": self.config,
                            "notes": [
                                {
                                    "index": note.index,
                                    "left": note.left,
                                    "right": note.right,
                                    "target": note.target,
                                }
                                for note in notes
                            ],
                        },
                    )

                if self.start_performance:
                    pending_initial_debug = save_initial_debug
                else:
                    save_initial_debug()

                pointer_delay_ms = int(
                    self.config["session"].get("pointer_start_delay_ms", 0)
                )
                remaining_delay_s = _remaining_pointer_start_delay_s(
                    start_wall,
                    pointer_delay_ms,
                    time.perf_counter(),
                )
                if remaining_delay_s > 0:
                    LOGGER.info(
                        "Waiting %.0fms before pointer tracking (configured=%dms)",
                        remaining_delay_s * 1000.0,
                        pointer_delay_ms,
                    )
                    self.abort_event.wait(remaining_delay_s)

                state = SessionState.TRACKING_POINTER
                tracking_started_wall = time.perf_counter()
                first_timestamp: float | None = None
                pointer_acquired = False
                pointer_search_expand_ms = int(
                    self.config["tracking"].get("bootstrap_expand_ms", 150)
                )
                last_valid_pointer_at: float | None = None
                prediction_hold_s = float(self.config["tracking"].get("prediction_hold_ms", 90)) / 1000.0
                lost_timeout_s = float(self.config["session"].get("pointer_lost_timeout_ms", 320)) / 1000.0
                minimum_runtime_s = float(self.config["session"].get("minimum_runtime_ms", 250)) / 1000.0
                max_duration_s = float(self.config["session"].get("max_duration_s", 12.0))
                end_reason = "aborted"
                completed_at: float | None = None
                post_complete_observe_s = max(
                    0.0,
                    float(self.config["session"].get("post_complete_observe_ms", 150)) / 1000.0,
                )
                post_action_verifier: PostActionTrajectoryVerifier | None = None
                post_action_samples = max(
                    1,
                    int(self.config["tracking"].get("post_action_reanchor_samples", 3)),
                )
                freshness = _FrameFreshnessGuard(float(
                    self.config["session"].get("stale_frame_timeout_ms", 80),
                ))
                last_model_agreement = False
                last_captured = None

                while not self.abort_event.is_set():
                    captured = source.read()
                    last_captured = captured
                    self._remember_startup_frame(captured)
                    if self.abort_event.is_set():
                        break
                    if self.can_start is not None and not self.can_start():
                        self.abort_event.set()
                        break
                    frame_count += 1
                    if first_timestamp is None:
                        first_timestamp = captured.timestamp
                    elapsed = captured.timestamp - first_timestamp

                    capture_has_signal = _capture_has_signal(captured.image)
                    frame_is_fresh = freshness.observe(captured.timestamp, captured.image)

                    predicted = tracker.predict(captured.timestamp)
                    search_bounds = (
                        _pointer_bootstrap_search_bounds(
                            notes,
                            width,
                            elapsed,
                            pointer_search_expand_ms,
                            include_leading=(
                                self.start_performance
                                and not self.config["scheduler"].get("initial_skip_notes", 1)
                            ),
                        )
                        if predicted is None
                        else None
                    )
                    measurement = (
                        pointer_detector.detect(
                            captured.image,
                            predicted,
                            search_bounds=search_bounds,
                        )
                        if capture_has_signal and frame_is_fresh
                        else None
                    )
                    candidate_x = measurement.x if measurement is not None else None
                    accepted = False
                    post_action_state = ""
                    post_action_outcome = ""
                    if predicted is None:
                        confirmed = bootstrapper.update(captured.timestamp, measurement)
                        if confirmed is not None:
                            tracker.reset()
                            accepted = True
                            for sample in confirmed:
                                accepted = tracker.update(
                                    sample.timestamp,
                                    sample.measurement,
                                ) and accepted
                            if not accepted:
                                tracker.reset()
                            measurement = confirmed[-1].measurement
                            pointer_acquired = accepted
                            if pointer_acquired:
                                LOGGER.info(
                                    "Pointer acquired at x=%.1f after %.0fms (%d samples)",
                                    measurement.x,
                                    elapsed * 1000.0,
                                    len(confirmed),
                                )
                    else:
                        accepted = measurement is not None and tracker.update(
                            captured.timestamp,
                            measurement,
                        )

                    if accepted and measurement is not None and post_action_verifier is not None:
                        post_action_result = post_action_verifier.observe(
                            captured.timestamp,
                            measurement.x,
                        )
                        post_action_state = (
                            f"observing:{post_action_verifier.sample_count}/"
                            f"{post_action_verifier.required_samples}"
                        )
                        if post_action_result is not None:
                            tracker.reanchor_to_observation(
                                post_action_result.timestamp,
                                post_action_result.x,
                            )
                            post_action_outcome = post_action_result.outcome
                            post_action_state = f"applied:{post_action_result.sample_count}"
                            LOGGER.info(
                                "Post-action trajectory %s: x=%.1f samples=%d "
                                "continuation_error=%.1f snap_error=%.1f",
                                post_action_result.outcome,
                                post_action_result.x,
                                post_action_result.sample_count,
                                post_action_result.continuation_error,
                                post_action_result.snap_error,
                            )
                            post_action_verifier = None

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
                            and measurement is not None
                            and tracker.model_agrees_with_observation(captured.timestamp, measurement.x)
                            and next_note is not None
                            and next_note.right - next_note.left <= model_max_width
                        )
                        last_model_agreement = (
                            not tracker.has_locked_speed
                            or tracker.model_agrees_with_observation(captured.timestamp, measurement.x)
                        )
                        pointer_for_schedule = (
                            tracker.predict(captured.timestamp)
                            if schedule_uses_model
                            else tracker.last_x
                        )
                        last_valid_pointer_at = captured.timestamp
                    elif (
                        capture_has_signal
                        and frame_is_fresh
                        and last_model_agreement
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
                            observed_x=measured_x,
                        )
                        event_labels.extend(f"M{note.index}" for note in update.newly_missed)
                        for note in update.due:
                            if self.abort_event.is_set():
                                break
                            if post_action_verifier is not None:
                                partial_result = post_action_verifier.finish()
                                if partial_result is not None:
                                    tracker.reanchor_to_observation(
                                        partial_result.timestamp,
                                        partial_result.x,
                                    )
                                    post_action_outcome = partial_result.outcome
                                    LOGGER.info(
                                        "Post-action trajectory %s applied early from %d sample(s)",
                                        partial_result.outcome,
                                        partial_result.sample_count,
                                    )
                                post_action_verifier = None
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
                            # Submitting a click does not prove that the game
                            # accepted it. Freeze speed only after a sufficiently
                            # long, stable fit; otherwise keep learning through
                            # the first short interval before the next note.
                            expected_action_x = tracker.predict(action_started)
                            if (
                                expected_action_x is not None
                                and tracker.try_lock_session_speed(action_started)
                                and tracker.speed is not None
                            ):
                                action_latency_s = (
                                    scheduler.model_latency_s
                                    if schedule_uses_model
                                    else scheduler.latency_s
                                )
                                post_action_verifier = PostActionTrajectoryVerifier(
                                    action_timestamp=action_started,
                                    expected_x=expected_action_x,
                                    note_target=note.target,
                                    speed=tracker.speed,
                                    input_latency_s=action_latency_s,
                                    required_samples=post_action_samples,
                                )
                                post_action_state = f"observing:0/{post_action_samples}"
                        if update.newly_missed:
                            LOGGER.debug(
                                "Missed notes: %s",
                                [note.index for note in update.newly_missed],
                            )

                    overlay = draw_overlay(captured.image, notes, note_band, shown_measurement, tracker.speed)
                    if frame_count == 1:
                        recorder.save_image("pointer_search_start.jpg", overlay)
                    if pointer_acquired:
                        recorder.save_image("pointer_locked.jpg", overlay)
                        pointer_acquired = False
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
                        candidate_x=candidate_x,
                        acquisition_state=(
                            "tracking"
                            if tracker.last_x is not None
                            else f"confirming:{bootstrapper.sample_count}"
                        ),
                        search_left=search_bounds[0] if search_bounds is not None else None,
                        search_right=search_bounds[1] if search_bounds is not None else None,
                        post_action_state=post_action_state,
                        post_action_outcome=post_action_outcome,
                        raw_frame=captured.image,
                        frame_is_fresh=frame_is_fresh,
                        speed_locked=tracker.has_locked_speed,
                        model_x=tracker.predict(captured.timestamp),
                        model_error=(
                            tracker.predict(captured.timestamp) - measured_x
                            if measured_x is not None and tracker.predict(captured.timestamp) is not None else None
                        ),
                        speed_fit_span_ms=tracker.speed_fit_span_ms,
                        speed_fit_r_squared=tracker.last_fit.r_squared if tracker.last_fit is not None else None,
                    )

                    if scheduler.complete:
                        state = SessionState.FINISHED
                        if completed_at is None:
                            completed_at = captured.timestamp
                        if captured.timestamp - completed_at >= post_complete_observe_s:
                            end_reason = "all_notes_processed"
                            break
                        continue
                    if elapsed >= max_duration_s:
                        LOGGER.warning("Session timed out after %.2fs", elapsed)
                        state = SessionState.FINISHED
                        end_reason = "timeout"
                        break
                    if (
                        elapsed >= minimum_runtime_s
                        and last_valid_pointer_at is not None
                        and captured.timestamp - last_valid_pointer_at >= lost_timeout_s
                    ):
                        LOGGER.info("Pointer lost for %.0fms; ending session", lost_timeout_s * 1000)
                        state = SessionState.FINISHED
                        end_reason = "pointer_lost"
                        break

                if self.abort_event.is_set():
                    state = SessionState.ABORTED
                    end_reason = "aborted"

                if last_captured is not None:
                    recorder.save_image("final_capture.png", last_captured.image)
                recorder.save_json("session_result.json", {
                    "end_reason": end_reason,
                    "elapsed_s": elapsed if first_timestamp is not None else 0.0,
                    "max_duration_s": max_duration_s,
                    "pending_count": scheduler.pending_count,
                    "submitted_click_count": sum(note.status == "hit" for note in notes),
                    "skipped_or_missed_count": sum(note.status == "missed" for note in notes),
                })

                duration = max(time.perf_counter() - tracking_started_wall, 1e-6)
                return SessionResult(
                    state=state,
                    note_count=len(notes),
                    hit_count=sum(note.status == "hit" for note in notes),
                    missed_count=sum(note.status == "missed" for note in notes),
                    frame_count=frame_count,
                    average_fps=frame_count / duration,
                )
        except _SessionInterrupted:
            LOGGER.info("演奏启动已取消")
            return SessionResult(SessionState.ABORTED, 0, 0, 0, frame_count, 0.0)
        finally:
            try:
                if pending_initial_debug is not None:
                    pending_initial_debug()
                if self._startup_frames:
                    if recorder is None:
                        image = self._startup_frames[0][1]
                        recorder = DebugRecorder(
                            self.config["debug"], (image.shape[1], image.shape[0]),
                            int(capture_cfg["target_fps"]),
                        )
                        recorder.save_json("startup_result.json", {
                            "end_reason": "startup_did_not_enter_tracking",
                            "config": self.config,
                        })
                    frames = []
                    for index, (timestamp, image) in enumerate(self._startup_frames):
                        name = f"startup_{index:03d}_raw.png"
                        recorder.save_image(name, image)
                        frames.append({"image": name, "timestamp": timestamp})
                    recorder.save_json("startup_frames.json", {
                        "capture_ready_at": self.capture_ready_at,
                        "startup_input_timestamps": self.startup_input_timestamps,
                        "frames": frames,
                    })
                    self._startup_frames.clear()
            finally:
                try:
                    if recorder is not None:
                        recorder.close()
                finally:
                    if owns_action:
                        action.close()
