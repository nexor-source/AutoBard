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
        self._fallback_speed: float | None = None
        self._fallback_until: float = 0.0
        self._trajectory_timestamp: float | None = None
        self._trajectory_x: float | None = None
        self._session_speed: float | None = None

    def reset(self) -> None:
        self.estimator.reset()
        self.last_timestamp = None
        self.last_x = None
        self.last_confidence = 0.0
        self.last_fit = None
        self._fallback_speed = None
        self._fallback_until = 0.0
        self._trajectory_timestamp = None
        self._trajectory_x = None
        self._session_speed = None

    def _valid_speed(self, fit: SpeedFit | None) -> float | None:
        if fit is None:
            return None
        speed = fit.speed
        if not (
            float(self.config.get("min_speed_px_s", 20.0))
            <= speed
            <= float(self.config.get("max_speed_px_s", 3000.0))
        ):
            return None
        return speed

    @property
    def speed(self) -> float | None:
        if self._session_speed is not None:
            return self._session_speed
        fitted = self._valid_speed(self.last_fit)
        if fitted is not None:
            return fitted
        if (
            self._fallback_speed is not None
            and self.last_timestamp is not None
            and self.last_timestamp <= self._fallback_until
        ):
            return self._fallback_speed
        return None

    def predict(self, timestamp: float) -> float | None:
        if self.last_x is None or self.last_timestamp is None:
            return None
        if (
            self._session_speed is not None
            and self._trajectory_timestamp is not None
            and self._trajectory_x is not None
        ):
            return self._trajectory_x + self._session_speed * max(
                0.0, timestamp - self._trajectory_timestamp
            )
        fitted = self._valid_speed(self.last_fit)
        if fitted is not None:
            return self.last_x + fitted * max(0.0, timestamp - self.last_timestamp)
        if (
            self._fallback_speed is not None
            and self._trajectory_timestamp is not None
            and self._trajectory_x is not None
            and timestamp <= self._fallback_until
        ):
            return self._trajectory_x + self._fallback_speed * max(
                0.0, timestamp - self._trajectory_timestamp
            )
        return self.last_x

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
        if self._session_speed is not None:
            # The game keeps one constant speed for the complete performance.
            # Measurements still correct position, but post-hit note-center
            # jitter must never produce a replacement speed estimate.
            return True
        self.estimator.add(timestamp, x, measurement.confidence)
        self.last_fit = self.estimator.fit()
        fitted = self._valid_speed(self.last_fit)
        if fitted is not None:
            hold_s = max(0.0, float(self.config.get("speed_hold_ms", 500)) / 1000.0)
            self._fallback_speed = fitted
            self._fallback_until = float(timestamp) + hold_s
            self._trajectory_timestamp = float(timestamp)
            self._trajectory_x = float(x)
        return True

    def reanchor_after_hit(self, timestamp: float, note_center_x: float) -> None:
        """Start a new motion segment after the game snaps the pointer to a hit note."""
        preserved_speed = self.speed
        hold_s = max(0.0, float(self.config.get("speed_hold_ms", 500)) / 1000.0)

        if self._session_speed is None and preserved_speed is not None:
            self._session_speed = preserved_speed

        self.estimator.reset()
        self.last_timestamp = float(timestamp)
        self.last_x = float(note_center_x)
        self.last_confidence = 1.0
        self.last_fit = None
        self.estimator.add(timestamp, note_center_x, 1.0)

        self._fallback_speed = preserved_speed
        self._fallback_until = float(timestamp) + hold_s if preserved_speed is not None else 0.0
        self._trajectory_timestamp = float(timestamp)
        self._trajectory_x = float(note_center_x)
