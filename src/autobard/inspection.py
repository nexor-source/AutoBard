from __future__ import annotations

from pathlib import Path

import cv2

from .debug.overlay import draw_overlay
from .models import Rect
from .vision.bar_locator import locate_bar_candidates
from .vision.notes import NoteDetector


def inspect_image(image_path: str | Path, config: dict, output_path: str | Path, auto_locate: bool = False) -> None:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(image_path)

    working = image
    capture_origin = (0, 0)
    if auto_locate:
        candidates = locate_bar_candidates(image)
        if not candidates:
            raise RuntimeError("No likely horizontal bar found")
        candidate = candidates[0].rect
        working = candidate.crop(image)
        capture_origin = (candidate.left, candidate.top)

    height, width = working.shape[:2]
    note_band = Rect(0, 0, width, height).subrect_from_normalized(config["vision"]["note_band_normalized"])
    result = NoteDetector(config["vision"]["notes"]).detect(note_band.crop(working))
    notes = result.notes
    for note in notes:
        note.left += note_band.left
        note.right += note_band.left
        note.target += note_band.left
    overlay = draw_overlay(working, notes, note_band)
    cv2.imwrite(str(output_path), overlay)
    mask_path = Path(output_path).with_name(Path(output_path).stem + "_mask.png")
    cv2.imwrite(str(mask_path), result.mask)
    print(f"Detected {len(notes)} notes; output={output_path}; mask={mask_path}; origin={capture_origin}")
