"""Short session cues on a separate worker so sound never delays a note."""

from __future__ import annotations

import logging
import os
import queue
import threading

LOGGER = logging.getLogger(__name__)


class SessionSounds:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=8)
        self._closed = False
        self._thread: threading.Thread | None = None
        if enabled:
            self._thread = threading.Thread(target=self._run, name="autobard-sounds", daemon=True)
            self._thread.start()

    def play(self, cue: str) -> None:
        if not self.enabled or self._closed:
            return
        try:
            self._queue.put_nowait(cue)
        except queue.Full:
            LOGGER.debug("Sound queue full; skipped %s cue", cue)

    @staticmethod
    def _play(cue: str) -> None:
        if os.name == "nt":
            import winsound

            # Rising pitch for takeover, falling pitch for the end of a session.
            for frequency in ((850, 1150) if cue == "takeover" else (1050, 700)):
                winsound.Beep(frequency, 45)

    def _run(self) -> None:
        while True:
            cue = self._queue.get()
            if cue is None:
                return
            try:
                self._play(cue)
            except Exception:
                LOGGER.warning("提示音播放失败", exc_info=True)

    def close(self) -> None:
        self._closed = True
        if self._thread is None:
            return
        # Discard queued cues on shutdown instead of playing stale notifications.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put_nowait(None)
        self._thread.join(timeout=0.25)
