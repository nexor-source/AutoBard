from __future__ import annotations

import logging

from autobard.models import Rect

from .base import CaptureSource
from .mss_capture import MSSCapture

LOGGER = logging.getLogger(__name__)


def create_capture(backend: str, region: Rect, target_fps: int) -> CaptureSource:
    requested = backend.casefold()
    if requested not in {"auto", "dxcam", "mss"}:
        raise ValueError(f"Unsupported capture backend: {backend}")

    if requested in {"auto", "dxcam"}:
        try:
            import dxcam  # noqa: F401
            from .dxcam_capture import DXCamCapture

            return DXCamCapture(region, target_fps)
        except Exception as exc:
            if requested == "dxcam":
                raise RuntimeError("DXcam is unavailable") from exc
            LOGGER.info("DXcam unavailable; falling back to MSS: %s", exc)

    return MSSCapture(region, target_fps)
