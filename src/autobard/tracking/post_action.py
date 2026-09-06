from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True, slots=True)
class PostActionTrajectoryResult:
    timestamp: float
    x: float
    outcome: str
    sample_count: int
    continuation_error: float
    snap_error: float


class PostActionTrajectoryVerifier:
    """Re-anchor a constant-speed trajectory from observations after an action.

    A submitted click is not proof that the game accepted the hit.  The next
    measurements tell us where the pointer actually went, regardless of
    whether it snapped to the note or continued past it.
    """

    def __init__(
        self,
        *,
        action_timestamp: float,
        expected_x: float,
        note_target: float,
        speed: float,
        input_latency_s: float,
        required_samples: int = 3,
    ) -> None:
        self.action_timestamp = float(action_timestamp)
        self.expected_x = float(expected_x)
        self.note_target = float(note_target)
        self.speed = float(speed)
        self.input_latency_s = max(0.0, float(input_latency_s))
        self.required_samples = max(1, int(required_samples))
        self._samples: list[tuple[float, float]] = []

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def observe(self, timestamp: float, x: float) -> PostActionTrajectoryResult | None:
        if timestamp <= self.action_timestamp:
            return None
        self._samples.append((float(timestamp), float(x)))
        if len(self._samples) < self.required_samples:
            return None
        return self.finish()

    def finish(self) -> PostActionTrajectoryResult | None:
        if not self._samples:
            return None

        anchor_timestamp = self._samples[-1][0]
        projected = [
            x + self.speed * (anchor_timestamp - timestamp)
            for timestamp, x in self._samples
        ]
        anchor_x = float(median(projected))

        continuation_errors: list[float] = []
        snap_errors: list[float] = []
        receipt_timestamp = self.action_timestamp + self.input_latency_s
        for timestamp, x in self._samples:
            continuation_x = self.expected_x + self.speed * (
                timestamp - self.action_timestamp
            )
            if timestamp <= receipt_timestamp:
                snap_x = continuation_x
            else:
                snap_x = self.note_target + self.speed * (
                    timestamp - receipt_timestamp
                )
            continuation_errors.append(abs(x - continuation_x))
            snap_errors.append(abs(x - snap_x))

        continuation_error = float(median(continuation_errors))
        snap_error = float(median(snap_errors))
        outcome = "snap-like" if snap_error + 1.0 < continuation_error else "continuous"
        return PostActionTrajectoryResult(
            timestamp=anchor_timestamp,
            x=anchor_x,
            outcome=outcome,
            sample_count=len(self._samples),
            continuation_error=continuation_error,
            snap_error=snap_error,
        )
