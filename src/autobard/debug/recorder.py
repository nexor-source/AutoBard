from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


class DebugRecorder:
    def __init__(self, config: dict, frame_size: tuple[int, int], fps: int) -> None:
        self.enabled = bool(config.get("enabled", False))
        self.save_every = int(config.get("save_every_n_frames", 0))
        self.record_video = bool(config.get("record_video", False))
        self.event_follow_frames = max(0, int(config.get("event_follow_frames", 6)))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.directory = Path(config.get("output_dir", "debug_output")) / stamp
        self.csv_handle = None
        self.csv_writer = None
        self.video = None
        self._event_index = 0
        self._event_label = ""
        self._event_remaining = 0
        self._event_offset = 0
        self._event_images: list[tuple[str, np.ndarray]] = []
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
            "schedule_mode",
            "action_submit_delay_ms",
            "action_call_ms",
            "candidate_x",
            "acquisition_state",
            "search_left",
            "search_right",
            "post_action_state",
            "post_action_outcome",
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

    def save_json(self, name: str, value: object) -> None:
        if self.enabled:
            with (self.directory / name).open("w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)

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
        schedule_mode: str = "",
        action_submit_delay_ms: str = "",
        action_call_ms: str = "",
        candidate_x: float | None = None,
        acquisition_state: str = "",
        search_left: float | None = None,
        search_right: float | None = None,
        post_action_state: str = "",
        post_action_outcome: str = "",
        raw_frame: np.ndarray | None = None,
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
            schedule_mode,
            action_submit_delay_ms,
            action_call_ms,
            candidate_x,
            acquisition_state,
            search_left,
            search_right,
            post_action_state,
            post_action_outcome,
        ])
        if any(part.startswith("H") for part in events.split(";")):
            self._event_index += 1
            self._event_label = events.replace(";", "_")
            self._event_remaining = self.event_follow_frames + 1
            self._event_offset = 0
        if self._event_remaining > 0:
            name = (
                f"event_{self._event_index:02d}_{self._event_label}_"
                f"f{frame_index:05d}_p{self._event_offset:02d}.jpg"
            )
            self._event_images.append((name, overlay.copy()))
            if raw_frame is not None:
                self._event_images.append((name.removesuffix(".jpg") + "_raw.png", raw_frame.copy()))
            self._event_remaining -= 1
            self._event_offset += 1
        if self.video is not None:
            self.video.write(overlay)
        if self.save_every > 0 and frame_index % self.save_every == 0:
            cv2.imwrite(str(self.directory / f"frame_{frame_index:05d}.jpg"), overlay)

    def close(self) -> None:
        if self.enabled:
            for name, image in self._event_images:
                cv2.imwrite(str(self.directory / name), image)
        self._event_images.clear()
        if self.video is not None:
            self.video.release()
            self.video = None
        if self.csv_handle is not None:
            self.csv_handle.close()
            self.csv_handle = None
