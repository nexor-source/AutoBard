from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class SpeedFit:
    speed: float
    intercept: float
    r_squared: float
    sample_count: int


class RobustSpeedEstimator:
    def __init__(self, history_size: int = 18, min_samples: int = 4) -> None:
        self.samples: deque[tuple[float, float, float]] = deque(maxlen=history_size)
        self.min_samples = min_samples

    def reset(self) -> None:
        self.samples.clear()

    def add(self, timestamp: float, x: float, confidence: float = 1.0) -> None:
        self.samples.append((float(timestamp), float(x), float(confidence)))

    def fit(self) -> SpeedFit | None:
        if len(self.samples) < self.min_samples:
            return None
        data = np.asarray(self.samples, dtype=np.float64)
        t = data[:, 0] - data[0, 0]
        x = data[:, 1]
        w = np.clip(data[:, 2], 0.05, 1.0)
        if np.ptp(t) < 1e-6:
            return None

        design = np.column_stack((t, np.ones_like(t)))
        weighted = design * np.sqrt(w[:, None])
        target = x * np.sqrt(w)
        coef, *_ = np.linalg.lstsq(weighted, target, rcond=None)
        predicted = design @ coef
        residual = x - predicted
        median = np.median(residual)
        mad = np.median(np.abs(residual - median)) + 1e-6
        inliers = np.abs(residual - median) <= max(2.5 * mad, 1.5)
        if np.count_nonzero(inliers) >= self.min_samples and not np.all(inliers):
            design_i = design[inliers]
            w_i = w[inliers]
            weighted_i = design_i * np.sqrt(w_i[:, None])
            target_i = x[inliers] * np.sqrt(w_i)
            coef, *_ = np.linalg.lstsq(weighted_i, target_i, rcond=None)
            predicted = design @ coef

        ss_res = float(np.sum((x - predicted) ** 2))
        ss_tot = float(np.sum((x - np.mean(x)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0
        return SpeedFit(float(coef[0]), float(coef[1]), float(r_squared), len(self.samples))
