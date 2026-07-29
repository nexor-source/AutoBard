from __future__ import annotations

from autobard.models import PointerMeasurement

from .speed import RobustSpeedEstimator, SpeedFit


class PointerTracker:
    def __init__(self, config: dict, frame_width: int) -> None:
        self.config = config
        self.frame_width = frame_width
        self.estimator = RobustSpeedEstimator(
            history_size=int(config.get("history_size", 18)),
            min_samples=int(config.get("min_fit_samples", 4)),
        )
        self.last_timestamp: float | None = None
        self.last_x: float | None = None
        self.last_confidence: float = 0.0
        self.last_fit: SpeedFit | None = None

    def reset(self) -> None:
        self.estimator.reset()
        self.last_timestamp = None
        self.last_x = None
        self.last_confidence = 0.0
        self.last_fit = None

    @property
    def speed(self) -> float | None:
        if self.last_fit is None:
            return None
        speed = self.last_fit.speed
        if not (float(self.config.get("min_speed_px_s", 20.0)) <= speed <= float(self.config.get("max_speed_px_s", 3000.0))):
            return None
        return speed

    def predict(self, timestamp: float) -> float | None:
        if self.last_x is None or self.last_timestamp is None:
            return None
        speed = self.speed
        if speed is None:
            return self.last_x
        return self.last_x + speed * max(0.0, timestamp - self.last_timestamp)

    def update(self, timestamp: float, measurement: PointerMeasurement) -> bool:
        x = measurement.x
        if self.last_x is not None:
            backward_tolerance = self.frame_width * float(self.config.get("backward_tolerance_ratio", 0.025))
            if x < self.last_x - backward_tolerance:
                return False
            predicted = self.predict(timestamp)
            if predicted is not None and self.speed is not None:
                maximum_error = self.frame_width * float(self.config.get("max_prediction_error_ratio", 0.18))
                if abs(x - predicted) > maximum_error:
                    return False
        self.last_timestamp = float(timestamp)
        self.last_x = float(x)
        self.last_confidence = float(measurement.confidence)
        self.estimator.add(timestamp, x, measurement.confidence)
        self.last_fit = self.estimator.fit()
        return True
