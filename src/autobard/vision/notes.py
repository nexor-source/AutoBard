from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from autobard.models import Note

from .common import intervals_from_bool, merge_intervals, smooth_1d, warm_gold_score


@dataclass(slots=True)
class NoteDetectionResult:
    notes: list[Note]
    mask: np.ndarray
    column_score: np.ndarray
    threshold: float


class NoteDetector:
    """Detects note centers using adaptive warm-color coverage and 1-D geometry."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def detect(self, bgr: np.ndarray) -> NoteDetectionResult:
        if bgr.ndim != 3 or bgr.shape[2] < 3:
            raise ValueError("Note detector expects a BGR image")
        height, width = bgr.shape[:2]
        if width < 8 or height < 3:
            return NoteDetectionResult([], np.zeros((height, width), np.uint8), np.zeros(width), 1.0)

        score = warm_gold_score(bgr)
        pixel_quantile = float(self.config.get("pixel_quantile", 0.76))
        threshold = float(np.quantile(score, pixel_quantile))
        # Guard against a nearly uniform bright scene.
        threshold = max(threshold, float(np.median(score) + 0.08))
        mask = (score >= threshold).astype(np.uint8) * 255

        open_kernel = np.ones((max(1, round(height * 0.12)), 2), np.uint8)
        close_kernel = np.ones((max(1, round(height * 0.18)), max(2, round(width * 0.005))), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)

        coverage = np.mean(mask > 0, axis=0).astype(np.float32)
        weighted = np.percentile(score, 78, axis=0).astype(np.float32)
        column_score = smooth_1d(0.58 * coverage + 0.42 * weighted, kernel=max(3, round(width * 0.009)))

        minimum_coverage = float(self.config.get("column_coverage", 0.20))
        adaptive = float(np.median(column_score) + 1.8 * np.median(np.abs(column_score - np.median(column_score))))
        column_threshold = max(minimum_coverage, adaptive)
        active = column_score >= column_threshold
        # 1-D close/open avoids the old per-column Python loop.
        one_d = (active.astype(np.uint8) * 255).reshape(1, -1)
        close_w = max(2, round(width * float(self.config.get("merge_gap_ratio", 0.006))))
        one_d = cv2.morphologyEx(one_d, cv2.MORPH_CLOSE, np.ones((1, close_w), np.uint8))
        one_d = cv2.morphologyEx(one_d, cv2.MORPH_OPEN, np.ones((1, 2), np.uint8))
        intervals = intervals_from_bool(one_d.ravel() > 0)
        intervals = merge_intervals(intervals, max_gap=close_w)

        min_width = max(2, math.ceil(width * float(self.config.get("min_width_ratio", 0.009))))
        max_width = max(min_width + 1, round(width * float(self.config.get("max_width_ratio", 0.20))))
        minimum_confidence = float(self.config.get("min_confidence", 0.20))

        notes: list[Note] = []
        for left, right in intervals:
            interval_width = right - left
            if not (min_width <= interval_width <= max_width):
                continue
            segment = column_score[left:right]
            if segment.size == 0:
                continue
            xs = np.arange(left, right, dtype=np.float32)
            weights = np.maximum(segment - column_threshold + 0.02, 0.001)
            target = float(np.average(xs, weights=weights))
            confidence = float(np.clip(np.mean(segment), 0.0, 1.0))
            if confidence < minimum_confidence:
                continue
            notes.append(Note(len(notes), float(left), float(right), target, confidence))

        return NoteDetectionResult(notes, mask, column_score, column_threshold)
