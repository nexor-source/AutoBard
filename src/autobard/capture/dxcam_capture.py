from __future__ import annotations

import time

from autobard.models import CaptureFrame, Rect

from .base import CaptureSource


class DXCamCapture(CaptureSource):
    def __init__(self, region: Rect, target_fps: int) -> None:
        super().__init__(region, target_fps)
        self._camera = None

    def open(self) -> None:
        import dxcam

        self._camera = dxcam.create(output_color="BGR", max_buffer_len=2)
        self._camera.start(
            region=self.region.as_dxcam(),
            target_fps=self.target_fps,
            video_mode=True,
        )

    def read(self) -> CaptureFrame:
        if self._camera is None:
            raise RuntimeError("DXcam capture is not open")
        try:
            result = self._camera.get_latest_frame(with_timestamp=True)
            image, timestamp = result
        except TypeError:
            image = self._camera.get_latest_frame()
            timestamp = time.perf_counter()
        if image is None:
            raise RuntimeError("DXcam returned no frame")
        return CaptureFrame(image=image, timestamp=float(timestamp))

    def close(self) -> None:
        if self._camera is None:
            return
        try:
            if self._camera.is_capturing:
                self._camera.stop()
        finally:
            self._camera.release()
            self._camera = None
