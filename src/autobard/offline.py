from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .debug.overlay import draw_overlay
from .models import Note, PointerMeasurement, Rect
from .timing import NoteScheduler
from .tracking import PointerTracker
from .vision import NoteDetector, PointerDetector


@dataclass(slots=True)
class OfflineResult:
    frames: int
    notes: int
    hits: int
    missed: int
    output_video: Path
    output_csv: Path


def analyze_video(
    video_path: str | Path,
    config: dict,
    output_dir: str | Path,
    start_s: float = 0.0,
    roi_is_frame: bool = False,
) -> OfflineResult:
    source = cv2.VideoCapture(str(video_path))
    if not source.isOpened():
        raise FileNotFoundError(video_path)

    fps = float(source.get(cv2.CAP_PROP_FPS) or 60.0)
    source.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_s) * 1000.0)
    initial_count = max(1, int(config["session"].get("initial_note_frames", 5)))
    raw_initial: list[np.ndarray] = []
    for _ in range(initial_count):
        ok, frame = source.read()
        if not ok:
            source.release()
            raise RuntimeError("Video ended before the initial note frames were read")
        raw_initial.append(frame)

    full_height, full_width = raw_initial[0].shape[:2]
    full_rect = Rect(0, 0, full_width, full_height)
    roi = full_rect if roi_is_frame else Rect.from_normalized(full_rect, config["capture"]["roi_normalized"])
    initial_frames = [roi.crop(frame) for frame in raw_initial]
    initial = np.median(np.stack(initial_frames), axis=0).astype(np.uint8)
    height, width = initial.shape[:2]
    note_band = Rect(0, 0, width, height).subrect_from_normalized(config["vision"]["note_band_normalized"])
    note_result = NoteDetector(config["vision"]["notes"]).detect(note_band.crop(initial))
    notes: list[Note] = []
    for note in note_result.notes:
        note.left += note_band.left
        note.right += note_band.left
        note.target += note_band.left
        notes.append(note)
    if not notes:
        source.release()
        raise RuntimeError("No notes detected in the selected initial video frames")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    video_out = output / "offline_overlay.mp4"
    csv_out = output / "offline_tracking.csv"
    writer = cv2.VideoWriter(
        str(video_out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    csv_handle = csv_out.open("w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_handle)
    csv_writer.writerow(["frame", "time_s", "pointer_x", "confidence", "speed", "due_notes", "pending"])

    pointer_detector = PointerDetector(
        config["vision"]["pointer"],
        (float(config["vision"]["note_band_normalized"][1]),
         float(config["vision"]["note_band_normalized"][3])),
    )
    tracker = PointerTracker(config["tracking"], width)
    scheduler = NoteScheduler(notes, config["scheduler"], width)
    frame_index = 0

    try:
        # Re-process the median frame as a visual header; actual tracking begins on subsequent video frames.
        writer.write(draw_overlay(initial, notes, note_band))
        while True:
            ok, full_frame = source.read()
            if not ok:
                break
            frame = roi.crop(full_frame)
            timestamp = float(source.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            predicted = tracker.predict(timestamp)
            measurement = pointer_detector.detect(frame, predicted)
            accepted = measurement is not None and tracker.update(timestamp, measurement)
            shown: PointerMeasurement | None = measurement if accepted else None
            due_indices: list[int] = []
            if accepted and tracker.last_x is not None:
                update = scheduler.update(timestamp, tracker.last_x, tracker.speed)
                due_indices = [note.index for note in update.due]
            overlay = draw_overlay(frame, notes, note_band, shown, tracker.speed)
            writer.write(overlay)
            csv_writer.writerow([
                frame_index,
                f"{timestamp:.6f}",
                tracker.last_x if accepted else None,
                shown.confidence if shown else 0.0,
                tracker.speed,
                ",".join(map(str, due_indices)),
                scheduler.pending_count,
            ])
            frame_index += 1
    finally:
        source.release()
        writer.release()
        csv_handle.close()

    return OfflineResult(
        frames=frame_index,
        notes=len(notes),
        hits=sum(note.status == "hit" for note in notes),
        missed=sum(note.status == "missed" for note in notes),
        output_video=video_out,
        output_csv=csv_out,
    )
