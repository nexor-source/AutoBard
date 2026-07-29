from __future__ import annotations

import cv2
import numpy as np

from autobard.models import PointerMeasurement

from .common import robust_unit, smooth_1d, warm_gold_score


class PointerDetector:
    """Hybrid pointer detector: temporal motion + vertical edges + warm-color prior."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._previous_gray: np.ndarray | None = None

    def reset(self) -> None:
        self._previous_gray = None

    def _row_mask(self, height: int) -> np.ndarray:
        y0, y1 = self.config.get("analysis_y", [0.0, 1.0])
        row_mask = np.zeros(height, dtype=bool)
        start = max(0, min(height - 1, round(float(y0) * height)))
        end = max(start + 1, min(height, round(float(y1) * height)))
        row_mask[start:end] = True
        for excluded in self.config.get("excluded_y", []):
            e0, e1 = excluded
            a = max(0, min(height, round(float(e0) * height)))
            b = max(a, min(height, round(float(e1) * height)))
            row_mask[a:b] = False
        if not row_mask.any():
            row_mask[:] = True
        return row_mask

    def detect(self, bgr: np.ndarray, predicted_x: float | None = None) -> PointerMeasurement | None:
        height, width = bgr.shape[:2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        rows = self._row_mask(height)

        edge = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        edge_col = np.percentile(edge[rows, :], 80, axis=0)

        has_previous = self._previous_gray is not None and self._previous_gray.shape == gray.shape
        if not has_previous:
            motion_col = np.zeros(width, dtype=np.float32)
        else:
            diff = cv2.absdiff(gray, self._previous_gray)
            motion_col = np.percentile(diff[rows, :], 82, axis=0).astype(np.float32)
        self._previous_gray = gray
        # During a live session the pointer is moving. Waiting for one frame difference
        # is safer than locking the tracker onto a static note edge.
        if not has_previous and predicted_x is None:
            return None

        gold = warm_gold_score(bgr)
        color_col = np.percentile(gold[rows, :], 88, axis=0)

        motion = robust_unit(motion_col)
        edges = robust_unit(edge_col)
        color = robust_unit(color_col)
        combined = (
            float(self.config.get("motion_weight", 0.48)) * motion
            + float(self.config.get("edge_weight", 0.30)) * edges
            + float(self.config.get("color_weight", 0.22)) * color
        )
        combined = smooth_1d(combined, kernel=max(3, round(width * 0.007)))

        if predicted_x is not None and np.isfinite(predicted_x):
            sigma = max(2.0, width * float(self.config.get("prediction_sigma_ratio", 0.035)))
            xs = np.arange(width, dtype=np.float32)
            prior = np.exp(-0.5 * ((xs - float(predicted_x)) / sigma) ** 2)
            combined += float(self.config.get("prediction_weight", 0.45)) * prior

        peak_x = int(np.argmax(combined))
        peak = float(combined[peak_x])
        baseline = float(np.median(combined))
        spread = float(np.median(np.abs(combined - baseline)) + 1e-6)
        distinctness = float(np.clip((peak - baseline) / (6.0 * spread), 0.0, 1.0))
        confidence = float(np.clip(0.62 * peak + 0.38 * distinctness, 0.0, 1.0))
        if confidence < float(self.config.get("min_confidence", 0.20)):
            return None

        half_height = max(peak * 0.60, baseline + spread)
        left = peak_x
        right = peak_x
        max_width = max(2, round(width * float(self.config.get("max_width_ratio", 0.04))))
        while left > 0 and peak_x - left < max_width and combined[left - 1] >= half_height:
            left -= 1
        while right < width - 1 and right - peak_x < max_width and combined[right + 1] >= half_height:
            right += 1
        measured_x = float((left + right) / 2.0)
        return PointerMeasurement(measured_x, confidence, float(right - left + 1))
