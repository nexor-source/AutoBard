from __future__ import annotations

from abc import ABC, abstractmethod

from autobard.models import CaptureFrame, Rect


class CaptureSource(ABC):
    def __init__(self, region: Rect, target_fps: int) -> None:
        self.region = region
        self.target_fps = target_fps

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self) -> CaptureFrame:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "CaptureSource":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
