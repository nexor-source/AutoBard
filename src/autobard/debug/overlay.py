from __future__ import annotations

import cv2
import numpy as np

from autobard.models import Note, PointerMeasurement, Rect


def draw_overlay(
    frame: np.ndarray,
    notes: list[Note],
    note_band: Rect,
    pointer: PointerMeasurement | None = None,
    speed: float | None = None,
) -> np.ndarray:
    canvas = frame.copy()
    cv2.rectangle(canvas, (note_band.left, note_band.top), (note_band.right, note_band.bottom), (255, 255, 255), 1)
    for note in notes:
        color = (0, 255, 0) if note.status == "hit" else ((0, 0, 255) if note.status == "missed" else (0, 220, 255))
        left = round(note.left)
        right = round(note.right)
        target = round(note.target)
        cv2.rectangle(canvas, (left, note_band.top), (right, note_band.bottom), color, 1)
        cv2.line(canvas, (target, note_band.top - 5), (target, note_band.bottom + 5), color, 1)
    if pointer is not None:
        x = round(pointer.x)
        cv2.line(canvas, (x, 0), (x, canvas.shape[0] - 1), (255, 0, 255), 1)
        cv2.putText(canvas, f"x={pointer.x:.1f} conf={pointer.confidence:.2f}", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    if speed is not None:
        cv2.putText(canvas, f"v={speed:.1f}px/s", (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    return canvas
