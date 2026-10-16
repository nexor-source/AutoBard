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

    def detect(self, bgr: np.ndarray, *, strict_gold: bool = False) -> NoteDetectionResult:
        if bgr.ndim != 3 or bgr.shape[2] < 3:
            raise ValueError("Note detector expects a BGR image")
        height, width = bgr.shape[:2]
        if width < 8 or height < 3:
            return NoteDetectionResult([], np.zeros((height, width), np.uint8), np.zeros(width), 1.0)

        hsv = cv2.cvtColor(bgr[:, :, :3], cv2.COLOR_BGR2HSV)
        brightness = hsv[:, :, 2]
        brightness_p90 = float(np.percentile(brightness, 90))
        minimum_brightness_p90 = float(self.config.get("min_brightness_p90", 60))
        if brightness_p90 < minimum_brightness_p90:
            return NoteDetectionResult(
                [],
                np.zeros((height, width), np.uint8),
                np.zeros(width, dtype=np.float32),
                1.0,
            )

        if strict_gold:
            # Pending notes have a saturated orange core. Pale shoulders and
            # animated strings must not become additional notes or shift targets.
            score = (
                (hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 40)
                & (hsv[:, :, 1] >= 120) & (brightness >= 140)
            ).astype(np.float32)
            threshold = 0.5
        else:
            score = warm_gold_score(bgr)
            pixel_quantile = float(self.config.get("pixel_quantile", 0.76))
            threshold = float(np.quantile(score, pixel_quantile))
            # Guard against a nearly uniform bright scene.
            threshold = max(threshold, float(np.median(score) + 0.08))
        raw_gold_coverage = np.mean(score >= threshold, axis=0) if strict_gold else None
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
        column_threshold = 0.5 if strict_gold else max(minimum_coverage, adaptive)
        # Real note blocks fill most of the tightly calibrated note band. Thin
        # horizontal rails, text strokes, and pointer trails can have a strong
        # color score but do not cover enough rows to be notes.
        minimum_vertical_coverage = float(self.config.get("min_vertical_coverage", 0.68))
        active = (column_score >= column_threshold) & (coverage >= minimum_vertical_coverage)
        # 1-D close/open avoids the old per-column Python loop.
        one_d = (active.astype(np.uint8) * 255).reshape(1, -1)
        close_w = max(2, round(width * float(self.config.get("merge_gap_ratio", 0.006))))
        one_d = cv2.morphologyEx(one_d, cv2.MORPH_CLOSE, np.ones((1, close_w), np.uint8))
        one_d = cv2.morphologyEx(one_d, cv2.MORPH_OPEN, np.ones((1, 2), np.uint8))
        intervals = intervals_from_bool(one_d.ravel() > 0)
        intervals = merge_intervals(intervals, max_gap=close_w)

        # The bright core is reliable for finding a note, but its darker orange
        # shoulders are part of the same hit box. Expand only from an already
        # confirmed core, using a lower vertical-coverage threshold. This keeps
        # thin horizontal rails from becoming notes while making the reported
        # rectangle match the full visible note geometry.
        edge_vertical_coverage = float(self.config.get("edge_vertical_coverage", 0.35))
        edge_vertical_coverage = float(np.clip(edge_vertical_coverage, 0.0, minimum_vertical_coverage))
        expanded: list[tuple[int, int]] = []
        for left, right in intervals:
            while (
                left > 0
                and column_score[left - 1] >= column_threshold
                and coverage[left - 1] >= edge_vertical_coverage
            ):
                left -= 1
            while (
                right < width
                and column_score[right] >= column_threshold
                and coverage[right] >= edge_vertical_coverage
            ):
                right += 1
            expanded.append((left, right))
        intervals = merge_intervals(sorted(expanded), max_gap=close_w)

        # A dim shoulder may be split into several short support islands by a
        # glow/animation gap.  Attach those islands only to an already
        # confirmed note and only when the complete island stays inside a
        # small extension budget.  Rejecting (rather than clipping) islands
        # outside that budget prevents a nearby pointer trail from dragging a
        # wide first note far to the left.
        support = intervals_from_bool(coverage >= edge_vertical_coverage)
        shoulder_gap = max(
            1,
            round(width * float(self.config.get("shoulder_merge_gap_ratio", 0.012))),
        )
        shoulder_extension = max(
            2,
            round(width * float(self.config.get("shoulder_max_extension_ratio", 0.025))),
        )
        intervals = _attach_nearby_support(
            intervals,
            support,
            max_gap=shoulder_gap,
            max_extension=shoulder_extension,
        )

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
            # Brightness is asymmetric in the real artwork and biases a
            # weighted centroid slightly to the right. Timing should use the
            # geometric center of the complete hit box instead.
            target = float((left + right - 1) / 2.0)
            if raw_gold_coverage is not None:
                # Even-sized morphology can move a clipped startup component
                # right by one column. Include the original core at its edge.
                core_left, core_right = max(0, left - 2), min(width, right + 2)
                core = np.flatnonzero(raw_gold_coverage[core_left:core_right] >= minimum_vertical_coverage)
                if core.size:
                    target = float(core_left + (core[0] + core[-1]) / 2)
            confidence = float(np.clip(np.mean(segment), 0.0, 1.0))
            if confidence < minimum_confidence:
                continue
            notes.append(Note(len(notes), float(left), float(right), target, confidence))

        return NoteDetectionResult(notes, mask, column_score, column_threshold)


def _attach_nearby_support(
    confirmed: list[tuple[int, int]],
    support: list[tuple[int, int]],
    *,
    max_gap: int,
    max_extension: int,
) -> list[tuple[int, int]]:
    """Attach nearby low-coverage islands without creating new notes."""
    attached: list[tuple[int, int]] = []
    for original_left, original_right in confirmed:
        left, right = original_left, original_right
        changed = True
        while changed:
            changed = False
            for support_left, support_right in support:
                if support_right < left - max_gap or support_left > right + max_gap:
                    continue
                candidate_left = min(left, support_left)
                candidate_right = max(right, support_right)
                if original_left - candidate_left > max_extension:
                    continue
                if candidate_right - original_right > max_extension:
                    continue
                if candidate_left != left or candidate_right != right:
                    left, right = candidate_left, candidate_right
                    changed = True
        attached.append((left, right))
    return merge_intervals(sorted(attached), max_gap=0)
