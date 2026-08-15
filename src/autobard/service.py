from __future__ import annotations

import logging
import threading
import time

from pynput import keyboard, mouse

from .actions import create_action_sink
from .actions.base import ActionSink
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
        self.action: ActionSink | None = None
        interval_ms = float(config["hotkeys"].get("double_right_click_interval_ms", 350))
        self.double_right_click_interval_s = max(0.05, interval_ms / 1000.0)
        self.last_right_click_at: float | None = None

    def _start(self) -> None:
        self.start_event.set()

    def _on_click(self, _x: int, _y: int, button: mouse.Button, pressed: bool) -> None:
        if pressed or button != mouse.Button.right:
            return

        # Ignore mouse input produced while a session is active. In system_input
        # mode note hits may themselves be right clicks and must not retrigger it.
        if self.worker is not None and self.worker.is_alive():
            self.last_right_click_at = None
            return

        now = time.monotonic()
        if (
            self.last_right_click_at is not None
            and now - self.last_right_click_at <= self.double_right_click_interval_s
        ):
            self.last_right_click_at = None
            self._start()
        else:
            self.last_right_click_at = now

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
            session = AutoBardSession(self.config, capture_rect, self.action)
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
            str(hotkeys["abort"]): self._abort,
            str(hotkeys["quit"]): self._quit,
        }
        self.action = create_action_sink(self.config["action"])
        try:
            interval_ms = round(self.double_right_click_interval_s * 1000)
            print(
                f"AutoBard online: start=double-right-click ({interval_ms}ms) "
                f"abort={hotkeys['abort']} quit={hotkeys['quit']}"
            )
            with keyboard.GlobalHotKeys(mapping) as keyboard_listener, mouse.Listener(
                on_click=self._on_click
            ) as mouse_listener:
                while not self.quit_event.wait(0.05):
                    if self.start_event.is_set():
                        self.start_event.clear()
                        if self.worker is None or not self.worker.is_alive():
                            self.worker = threading.Thread(target=self._run_session, daemon=True)
                            self.worker.start()
                        else:
                            LOGGER.warning("A session is already running")
                keyboard_listener.stop()
                mouse_listener.stop()
            if self.worker is not None:
                self.worker.join(timeout=2.0)
        finally:
            self.action.close()
            self.action = None
