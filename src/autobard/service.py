from __future__ import annotations

import logging
import threading

from pynput import keyboard

from .runtime import AutoBardSession
from .window import resolve_capture_rect

LOGGER = logging.getLogger(__name__)


class HotkeyService:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.quit_event = threading.Event()
        self.start_event = threading.Event()
        self.active_session: AutoBardSession | None = None
        self.worker: threading.Thread | None = None

    def _start(self) -> None:
        self.start_event.set()

    def _abort(self) -> None:
        if self.active_session is not None:
            self.active_session.abort()

    def _quit(self) -> None:
        self._abort()
        self.quit_event.set()

    def _run_session(self) -> None:
        try:
            parent, capture_rect = resolve_capture_rect(self.config)
            LOGGER.info("Window/monitor rect=%s capture rect=%s", parent, capture_rect)
            session = AutoBardSession(self.config, capture_rect)
            self.active_session = session
            result = session.run()
            LOGGER.info(
                "Session %s: notes=%d hits=%d missed=%d frames=%d fps=%.1f",
                result.state.name,
                result.note_count,
                result.hit_count,
                result.missed_count,
                result.frame_count,
                result.average_fps,
            )
        except Exception:
            LOGGER.exception("Session failed")
        finally:
            self.active_session = None

    def run(self) -> None:
        hotkeys = self.config["hotkeys"]
        mapping = {
            str(hotkeys["start"]): self._start,
            str(hotkeys["abort"]): self._abort,
            str(hotkeys["quit"]): self._quit,
        }
        print(f"AutoBard online: start={hotkeys['start']} abort={hotkeys['abort']} quit={hotkeys['quit']}")
        with keyboard.GlobalHotKeys(mapping) as listener:
            while not self.quit_event.wait(0.05):
                if self.start_event.is_set():
                    self.start_event.clear()
                    if self.worker is None or not self.worker.is_alive():
                        self.worker = threading.Thread(target=self._run_session, daemon=True)
                        self.worker.start()
                    else:
                        LOGGER.warning("A session is already running")
            listener.stop()
        if self.worker is not None:
            self.worker.join(timeout=2.0)
