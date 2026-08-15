from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

from autobard.models import Note

from .base import ActionSink

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
KEYEVENTF_KEYUP = 0x0002

VK_CODES = {
    "space": 0x20,
    "f": 0x46,
    "e": 0x45,
}

ULONG_PTR = wintypes.WPARAM
LOGGER = logging.getLogger("autobard.action")


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


def _send(item: INPUT) -> None:
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
    if sent != 1:
        raise ctypes.WinError()


def _mouse(flags: int) -> None:
    _send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, flags, 0, 0)))


def _legacy_mouse_event(flags: int) -> None:
    ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)


def _key(vk: int, flags: int = 0) -> None:
    _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0)))


def _release_mouse_right() -> None:
    try:
        _mouse(MOUSEEVENTF_RIGHTUP)
    except Exception:
        LOGGER.exception("Failed to release mouse_right")


class SendInputAction(ActionSink):
    def __init__(self, kind: str, key: str, press_duration_ms: int, mouse_backend: str = "send_input") -> None:
        if os.name != "nt":
            raise RuntimeError("SendInput is available only on Windows")
        self.kind = kind
        self.key = key.casefold()
        self.duration = max(0.0, press_duration_ms / 1000.0)
        self.mouse_backend = mouse_backend.casefold()
        if self.mouse_backend not in {"send_input", "mouse_event"}:
            raise ValueError(f"Unsupported mouse input backend: {mouse_backend}")

    def hit_note(self, note: Note, timestamp: float) -> None:
        if self.kind == "mouse_right":
            if self.mouse_backend == "mouse_event":
                # Match the working legacy implementation exactly: the deprecated
                # mouse_event API and a synchronous down/hold/up sequence.
                _legacy_mouse_event(MOUSEEVENTF_RIGHTDOWN)
                if self.duration:
                    time.sleep(self.duration)
                _legacy_mouse_event(MOUSEEVENTF_RIGHTUP)
                LOGGER.info(
                    "MOUSE-EVENT mouse_right note=%d target=%.1f duration_ms=%.0f t=%.6f",
                    note.index,
                    note.target,
                    self.duration * 1000,
                    timestamp,
                )
                return

            _mouse(MOUSEEVENTF_RIGHTDOWN)
            if self.duration:
                timer = threading.Timer(self.duration, _release_mouse_right)
                timer.daemon = True
                timer.start()
            else:
                _mouse(MOUSEEVENTF_RIGHTUP)
            LOGGER.info(
                "SYSTEM-INPUT mouse_right note=%d target=%.1f duration_ms=%.0f t=%.6f",
                note.index,
                note.target,
                self.duration * 1000,
                timestamp,
            )
            return
        if self.kind == "key":
            vk = VK_CODES.get(self.key)
            if vk is None and len(self.key) == 1:
                vk = ord(self.key.upper())
            if vk is None:
                raise ValueError(f"Unsupported key: {self.key}")
            _key(vk)
            if self.duration:
                timer = threading.Timer(self.duration, _key, args=(vk, KEYEVENTF_KEYUP))
                timer.daemon = True
                timer.start()
            else:
                _key(vk, KEYEVENTF_KEYUP)
            return
        raise ValueError(f"Unsupported action kind: {self.kind}")
