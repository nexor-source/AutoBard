from __future__ import annotations

import time

import numpy as np

from autobard.models import CaptureFrame, Rect

from .base import CaptureSource


class MSSCapture(CaptureSource):
    def __init__(self, region: Rect, target_fps: int) -> None:
        super().__init__(region, target_fps)
        self._sct = None
        self._next_frame_at = 0.0

    def open(self) -> None:
        import mss

        self._sct = mss.mss()
        self._next_frame_at = time.perf_counter()

    def read(self) -> CaptureFrame:
        if self._sct is None:
            raise RuntimeError("MSS capture is not open")
        period = 1.0 / self.target_fps
        now = time.perf_counter()
        if now < self._next_frame_at:
            time.sleep(self._next_frame_at - now)
        shot = self._sct.grab(self.region.as_mss())
        timestamp = time.perf_counter()
        self._next_frame_at = max(self._next_frame_at + period, timestamp)
        # MSS is BGRA. Slicing the first three channels gives BGR without cvtColor.
        image = np.asarray(shot, dtype=np.uint8)[:, :, :3].copy()
        return CaptureFrame(image=image, timestamp=timestamp)

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None
