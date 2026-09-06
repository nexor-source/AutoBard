from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from autobard.models import PointerMeasurement

from .speed import RobustSpeedEstimator


@dataclass(frozen=True, slots=True)
class BootstrapSample:
    timestamp: float
    measurement: PointerMeasurement


class PointerBootstrapper:
    """Confirm real, right-moving pointer motion before starting a trajectory."""

    def __init__(self, config: dict, frame_width: int) -> None:
        self.confirm_frames = max(3, int(config.get("bootstrap_confirm_frames", 4)))
        self.min_displacement = max(
            1.5,
            frame_width
            * float(config.get("bootstrap_min_displacement_ratio", 0.003)),
        )
        self.backward_tolerance = max(
            1.5,
            frame_width * float(config.get("bootstrap_backward_tolerance_ratio", 0.004)),
        )
        self.min_speed = float(config.get("min_speed_px_s", 20.0))
        self.max_speed = float(config.get("max_speed_px_s", 3000.0))
        self.max_gap_s = max(
            0.02,
            float(config.get("bootstrap_max_gap_ms", 80)) / 1000.0,
        )
        self.min_r_squared = float(config.get("bootstrap_min_r_squared", 0.72))
        self._samples: deque[BootstrapSample] = deque(maxlen=self.confirm_frames)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def reset(self) -> None:
        self._samples.clear()

    def update(
        self,
        timestamp: float,
        measurement: PointerMeasurement | None,
    ) -> list[BootstrapSample] | None:
        if measurement is None:
            if (
                self._samples
                and timestamp - self._samples[-1].timestamp > self.max_gap_s
            ):
                self.reset()
            return None

        current = BootstrapSample(float(timestamp), measurement)
        if self._samples:
            previous = self._samples[-1]
            dt = current.timestamp - previous.timestamp
            dx = current.measurement.x - previous.measurement.x
            instantaneous_speed = dx / dt if dt > 1e-6 else float("inf")
            if (
                dt <= 0.0
                or dt > self.max_gap_s
                or dx < -self.backward_tolerance
                or instantaneous_speed > self.max_speed
            ):
                self.reset()

        self._samples.append(current)
        if len(self._samples) < self.confirm_frames:
            return None

        first = self._samples[0]
        last = self._samples[-1]
        displacement = last.measurement.x - first.measurement.x
        if displacement < self.min_displacement:
            return None
        estimator = RobustSpeedEstimator(
            history_size=self.confirm_frames,
            min_samples=self.confirm_frames,
        )
        for sample in self._samples:
            estimator.add(
                sample.timestamp,
                sample.measurement.x,
                sample.measurement.confidence,
            )
        fit = estimator.fit()
        if fit is None or not self.min_speed <= fit.speed <= self.max_speed:
            return None
        if fit.r_squared < self.min_r_squared:
            return None
        return list(self._samples)
