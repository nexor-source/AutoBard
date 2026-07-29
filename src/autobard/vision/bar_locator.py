from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from autobard.models import Rect


@dataclass(slots=True)
class BarCandidate:
    rect: Rect
    score: float


def locate_bar_candidates(bgr: np.ndarray, limit: int = 5) -> list[BarCandidate]:
    """Suggest likely horizontal performance bars; calibration remains the reliable fallback."""
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 45, 130)
    horizontal = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        np.ones((3, max(9, round(width * 0.03))), np.uint8),
    )
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[BarCandidate] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.14 or h < 5 or h > height * 0.20:
            continue
        aspect = w / max(h, 1)
        if aspect < 4.0 or y < height * 0.48:
            continue
        crop = gray[y:y + h, x:x + w]
        contrast = float(np.std(crop) / 64.0)
        bottom_bias = y / height
        width_ratio = w / width
        score = 0.45 * min(width_ratio / 0.35, 1.0) + 0.25 * min(aspect / 12.0, 1.0) + 0.20 * min(contrast, 1.0) + 0.10 * bottom_bias
        candidates.append(BarCandidate(Rect(x, y, x + w, y + h), score))
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:limit]
