from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .models import Rect


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def find_window_client_rect(title_contains: str) -> Rect | None:
    if os.name != "nt":
        return None

    enable_dpi_awareness()
    user32 = ctypes.windll.user32
    matches: list[int] = []

    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def enum_callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_contains.casefold() in buffer.value.casefold():
            matches.append(hwnd)
            return False
        return True

    callback = callback_type(enum_callback)
    user32.EnumWindows(callback, 0)
    if not matches:
        return None

    hwnd = matches[0]
    client = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        return None
    origin = wintypes.POINT(client.left, client.top)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = client.right - client.left
    height = client.bottom - client.top
    if width <= 0 or height <= 0:
        return None
    return Rect(origin.x, origin.y, origin.x + width, origin.y + height)


def primary_monitor_rect(monitor_index: int = 1) -> Rect:
    import mss

    with mss.mss() as sct:
        index = monitor_index if 0 < monitor_index < len(sct.monitors) else 1
        monitor = sct.monitors[index]
        return Rect(
            int(monitor["left"]),
            int(monitor["top"]),
            int(monitor["left"] + monitor["width"]),
            int(monitor["top"] + monitor["height"]),
        )


def resolve_capture_rect(config: dict) -> tuple[Rect, Rect]:
    window_cfg = config["window"]
    capture_cfg = config["capture"]
    parent = find_window_client_rect(str(window_cfg["title_contains"]))
    if parent is None:
        if not window_cfg.get("fallback_to_primary_monitor", True):
            raise RuntimeError(f"Window not found: {window_cfg['title_contains']}")
        parent = primary_monitor_rect(int(capture_cfg.get("monitor_index", 1)))
    return parent, Rect.from_normalized(parent, capture_cfg["roi_normalized"])
