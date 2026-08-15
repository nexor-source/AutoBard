from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


class DebugRecorder:
    def __init__(self, config: dict, frame_size: tuple[int, int], fps: int) -> None:
        self.enabled = bool(config.get("enabled", False))
        self.save_every = int(config.get("save_every_n_frames", 0))
        self.record_video = bool(config.get("record_video", False))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.directory = Path(config.get("output_dir", "debug_output")) / stamp
        self.csv_handle = None
        self.csv_writer = None
        self.video = None
        if not self.enabled:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self.csv_handle = (self.directory / "tracking.csv").open("w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_handle)
        self.csv_writer.writerow([
            "frame",
            "timestamp",
            "pointer_x",
            "measured_x",
            "confidence",
            "speed",
            "pending",
            "events",
        ])
        if self.record_video:
            width, height = frame_size
            self.video = cv2.VideoWriter(
                str(self.directory / "session.mp4"),
                cv2.VideoWriter_fourcc(*"mp4v"),
                float(fps),
                (width, height),
            )

    def save_image(self, name: str, image: np.ndarray) -> None:
        if self.enabled:
            cv2.imwrite(str(self.directory / name), image)

    def record(
        self,
        frame_index: int,
        timestamp: float,
        overlay: np.ndarray,
        pointer_x: float | None,
        confidence: float,
        speed: float | None,
        pending: int,
        measured_x: float | None = None,
        events: str = "",
    ) -> None:
        if not self.enabled:
            return
        assert self.csv_writer is not None
        self.csv_writer.writerow([
            frame_index,
            f"{timestamp:.9f}",
            pointer_x,
            measured_x,
            confidence,
            speed,
            pending,
            events,
        ])
        if self.video is not None:
            self.video.write(overlay)
        if self.save_every > 0 and frame_index % self.save_every == 0:
            cv2.imwrite(str(self.directory / f"frame_{frame_index:05d}.jpg"), overlay)

    def close(self) -> None:
        if self.video is not None:
            self.video.release()
            self.video = None
        if self.csv_handle is not None:
            self.csv_handle.close()
            self.csv_handle = None
