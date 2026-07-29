from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError(f"Invalid rectangle: {self}")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_dxcam(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def as_mss(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.top:self.bottom, self.left:self.right]

    def subrect_from_normalized(self, normalized: Iterable[float]) -> "Rect":
        x0, y0, x1, y1 = (float(v) for v in normalized)
        return Rect(
            left=max(0, min(self.width - 1, round(x0 * self.width))),
            top=max(0, min(self.height - 1, round(y0 * self.height))),
            right=max(1, min(self.width, round(x1 * self.width))),
            bottom=max(1, min(self.height, round(y1 * self.height))),
        )

    @classmethod
    def from_normalized(cls, parent: "Rect", normalized: Iterable[float]) -> "Rect":
        x0, y0, x1, y1 = (float(v) for v in normalized)
        return cls(
            left=parent.left + round(x0 * parent.width),
            top=parent.top + round(y0 * parent.height),
            right=parent.left + round(x1 * parent.width),
            bottom=parent.top + round(y1 * parent.height),
        )

    def to_normalized(self, parent: "Rect") -> list[float]:
        return [
            (self.left - parent.left) / parent.width,
            (self.top - parent.top) / parent.height,
            (self.right - parent.left) / parent.width,
            (self.bottom - parent.top) / parent.height,
        ]


@dataclass(slots=True)
class CaptureFrame:
    image: np.ndarray
    timestamp: float


@dataclass(slots=True)
class Note:
    index: int
    left: float
    right: float
    target: float
    confidence: float
    status: str = "pending"
    triggered_at: float | None = None


@dataclass(slots=True)
class PointerMeasurement:
    x: float
    confidence: float
    width: float


class SessionState(Enum):
    IDLE = auto()
    READING_NOTES = auto()
    TRACKING_POINTER = auto()
    FINISHED = auto()
    ABORTED = auto()
