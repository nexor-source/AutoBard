from __future__ import annotations

import cv2
import numpy as np


def robust_unit(values: np.ndarray, low_q: float = 5.0, high_q: float = 95.0) -> np.ndarray:
    array = values.astype(np.float32, copy=False)
    low = float(np.percentile(array, low_q))
    high = float(np.percentile(array, high_q))
    if high - low < 1e-6:
        return np.zeros_like(array, dtype=np.float32)
    return np.clip((array - low) / (high - low), 0.0, 1.0)


def warm_gold_score(bgr: np.ndarray) -> np.ndarray:
    """Brightness-independent score for warm, saturated pixels."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lightness = robust_unit(lab[:, :, 0])
    yellow_axis = robust_unit(lab[:, :, 2])
    saturation = robust_unit(hsv[:, :, 1])
    return 0.28 * lightness + 0.44 * yellow_axis + 0.28 * saturation


def smooth_1d(values: np.ndarray, kernel: int = 5) -> np.ndarray:
    kernel = max(1, int(kernel))
    if kernel % 2 == 0:
        kernel += 1
    if kernel == 1:
        return values.astype(np.float32, copy=True)
    return cv2.GaussianBlur(values.reshape(1, -1).astype(np.float32), (kernel, 1), 0).ravel()


def intervals_from_bool(active: np.ndarray) -> list[tuple[int, int]]:
    active = np.asarray(active, dtype=bool)
    if active.size == 0:
        return []
    padded = np.pad(active.astype(np.int8), (1, 1))
    transitions = np.diff(padded)
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends, strict=True)]


def merge_intervals(intervals: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    if not intervals:
        return []
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged
