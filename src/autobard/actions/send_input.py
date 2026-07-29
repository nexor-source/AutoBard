from __future__ import annotations

import ctypes
import os
import threading
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


def _key(vk: int, flags: int = 0) -> None:
    _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0)))


class SendInputAction(ActionSink):
    def __init__(self, kind: str, key: str, press_duration_ms: int) -> None:
        if os.name != "nt":
            raise RuntimeError("SendInput is available only on Windows")
        self.kind = kind
        self.key = key.casefold()
        self.duration = max(0.0, press_duration_ms / 1000.0)

    def hit_note(self, note: Note, timestamp: float) -> None:
        if self.kind == "mouse_right":
            _mouse(MOUSEEVENTF_RIGHTDOWN)
            if self.duration:
                timer = threading.Timer(self.duration, _mouse, args=(MOUSEEVENTF_RIGHTUP,))
                timer.daemon = True
                timer.start()
            else:
                _mouse(MOUSEEVENTF_RIGHTUP)
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
