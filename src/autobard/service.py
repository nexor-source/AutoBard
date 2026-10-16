from __future__ import annotations

import logging
import ctypes
import threading
import time

from pynput import keyboard, mouse

from .actions import create_action_sink
from .actions.base import ActionSink
from .feedback import SessionSounds
from .runtime import AutoBardSession
from .window import foreground_game_rect, resolve_capture_rect

LOGGER = logging.getLogger(__name__)


class HotkeyService:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.quit_event = threading.Event()
        self.start_event = threading.Event()
        self.ready_event = threading.Event()
        self.stopped_event = threading.Event()
        self.active_session: AutoBardSession | None = None
        self.worker: threading.Thread | None = None
        self.action: ActionSink | None = None
        interval_ms = float(config["hotkeys"].get("double_right_click_interval_ms", 350))
        self.double_right_click_interval_s = max(0.05, interval_ms / 1000.0)
        self.last_right_click_at: float | None = None
        self.trigger = str(config["hotkeys"].get("trigger", "double_right_click"))
        self._request_lock = threading.Lock()
        self._busy = False
        self._start_performance = False
        self._session_abort = threading.Event()
        self._last_scroll_at = float("-inf")
        self._finished_at = float("-inf")
        self.sounds: SessionSounds | None = None
        self._mouse_listener = None

    def _start(self, *, start_performance: bool = False) -> None:
        with self._request_lock:
            if self._busy or self.quit_event.is_set():
                return
            self._busy = True
            self._start_performance = start_performance
            self._session_abort.clear()
            self.start_event.set()

    def request_session(self) -> None:
        """Request one detection session from a GUI or another controller."""
        self._start()

    def _on_click(self, _x: int, _y: int, button: mouse.Button, pressed: bool) -> None:
        if self.trigger != "double_right_click" or pressed or button != mouse.Button.right:
            return

        # Ignore mouse input produced while a session is active. In system_input
        # mode note hits may themselves be right clicks and must not retrigger it.
        if self._busy or (self.worker is not None and self.worker.is_alive()):
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

    def _game_is_foreground(self) -> bool:
        title = str(self.config.get("window", {}).get("title_contains", "Dark and Darker"))
        return foreground_game_rect(title) is not None

    def _selected_scroll(self, dy: int) -> bool:
        return (
            (self.trigger == "scroll_up" and dy > 0)
            or (self.trigger == "scroll_down" and dy < 0)
        )

    def _filter_mouse_event(self, message: int, data) -> bool:
        # WH_MOUSE_LL: swallow only the chosen vertical wheel direction in game.
        # Dispatch it ourselves because suppress_event raises before on_scroll.
        if message != 0x020A or self.quit_event.is_set():  # WM_MOUSEWHEEL
            return True
        dy = ctypes.c_short(int(data.mouseData) >> 16).value
        if not self._selected_scroll(dy) or not self._game_is_foreground():
            return True
        self._on_scroll(data.pt.x, data.pt.y, 0, dy)
        if self._mouse_listener is not None:
            self._mouse_listener.suppress_event()
        return False

    def _on_scroll(self, _x: int, _y: int, _dx: int, dy: int) -> None:
        if not self._selected_scroll(dy):
            return
        now = time.monotonic()
        previous_scroll = self._last_scroll_at
        self._last_scroll_at = now
        # Require a fresh gesture after continuous scrolling or session completion.
        if now - previous_scroll < 0.35 or now - self._finished_at < 0.35:
            return
        if self._busy or not self._game_is_foreground():
            return
        self._start(start_performance=True)

    def _abort(self) -> None:
        with self._request_lock:
            self._session_abort.set()
            self.start_event.clear()
            if self.worker is None or not self.worker.is_alive():
                self._busy = False
        if self.active_session is not None:
            self.active_session.abort()

    def abort_session(self) -> None:
        self._abort()

    def _quit(self) -> None:
        self.quit_event.set()
        self._abort()

    def stop(self) -> None:
        self._quit()

    def _run_session(self) -> None:
        try:
            if self._session_abort.is_set():
                return
            start_performance = self._start_performance
            if start_performance and not self._game_is_foreground():
                LOGGER.info("已取消滚轮启动：游戏不在前台")
                return
            parent, capture_rect = resolve_capture_rect(self.config)
            LOGGER.info("Window/monitor rect=%s capture rect=%s", parent, capture_rect)
            session = AutoBardSession(
                self.config, capture_rect, self.action,
                start_performance=start_performance,
                abort_event=self._session_abort,
                can_start=self._game_is_foreground if start_performance else None,
                on_started=lambda: self.sounds.play("takeover") if self.sounds else None,
            )
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
            if self.sounds is not None:
                self.sounds.play("end")
            with self._request_lock:
                self._finished_at = time.monotonic()
                self._busy = False

    def run(self) -> None:
        self.quit_event.clear()
        self.ready_event.clear()
        self.stopped_event.clear()
        hotkeys = self.config["hotkeys"]
        mapping = {
            str(hotkeys["abort"]): self._abort,
            str(hotkeys["quit"]): self._quit,
        }
        try:
            self.action = create_action_sink(self.config["action"])
            self.sounds = SessionSounds(bool(self.config.get("feedback", {}).get("sound_enabled", True)))
            LOGGER.info(
                "AutoBard online: start=%s skip_first_note=%s abort=%s quit=%s",
                self.trigger,
                bool(self.config["scheduler"].get("initial_skip_notes", 1)),
                hotkeys["abort"],
                hotkeys["quit"],
            )
            self._mouse_listener = mouse.Listener(
                on_click=self._on_click, on_scroll=self._on_scroll,
                win32_event_filter=self._filter_mouse_event,
            )
            with keyboard.GlobalHotKeys(mapping) as keyboard_listener, self._mouse_listener as mouse_listener:
                self.ready_event.set()
                while not self.quit_event.wait(0.05):
                    with self._request_lock:
                        if self.start_event.is_set() and not self.quit_event.is_set():
                            self.start_event.clear()
                            if self._session_abort.is_set():
                                self._busy = False
                                continue
                            self.worker = threading.Thread(target=self._run_session, daemon=True)
                            self.worker.start()
                keyboard_listener.stop()
                mouse_listener.stop()
            if self.worker is not None:
                self.worker.join(timeout=2.0)
        finally:
            self._mouse_listener = None
            if self.sounds is not None:
                self.sounds.close()
                self.sounds = None
            if self.action is not None:
                self.action.close()
            self.action = None
            self.ready_event.clear()
            self.stopped_event.set()
