"""Passive countdown overlay and main-thread, borderless calibration wizard."""
from __future__ import annotations

import base64
import ctypes
import math
import os
import threading
import time
from dataclasses import dataclass
from tkinter import Canvas, PhotoImage, Toplevel, ttk

import cv2
from pynput import keyboard

from .calibration import _grab, prepare_calibration, save_calibration
from .models import Rect
from .window import foreground_game_rect, primary_monitor_rect


@dataclass(frozen=True)
class ImageViewport:
    left: int
    top: int
    width: int
    height: int
    source_width: int
    source_height: int

    @classmethod
    def fit(cls, source_width, source_height, width, height):
        available_width = max(1, width - 48)
        available_height = max(1, height - 170)
        scale = min(available_width / source_width, available_height / source_height)
        w, h = max(1, round(source_width * scale)), max(1, round(source_height * scale))
        return cls((width - w) // 2, 105 + (available_height - h) // 2,
                   w, h, source_width, source_height)

    def contains(self, x, y):
        return self.left <= x <= self.left + self.width and self.top <= y <= self.top + self.height

    def point(self, x, y):
        return (min(self.source_width, max(0, (x - self.left) * self.source_width / self.width)),
                min(self.source_height, max(0, (y - self.top) * self.source_height / self.height)))

    def selection(self, start, end):
        x0, y0 = self.point(*start)
        x1, y1 = self.point(*end)
        if abs(x1 - x0) < 2 or abs(y1 - y0) < 2:
            return None
        epsilon = 1e-7  # Avoid expanding an exact pixel boundary due to FP roundoff.
        return Rect(math.floor(min(x0, x1) + epsilon), math.floor(min(y0, y1) + epsilon),
                    math.ceil(max(x0, x1) - epsilon), math.ceil(max(y0, y1) - epsilon))


def _native_place(window, x, y, width, height, passive=False):
    window.update_idletasks()
    if os.name != "nt":
        window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        return
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.GetAncestor(window.winfo_id(), 2)
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    if passive:
        style = user32.GetWindowLongW(hwnd, -20)
        # NOACTIVATE, TOOLWINDOW, LAYERED, TRANSPARENT: hints neither take
        # keyboard focus nor intercept clicks intended for the game.
        user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x80 | 0x80000 | 0x20)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), x, y, width, height, 0x10)


class CalibrationHint:
    def __init__(self, root):
        self.window = Toplevel(root)
        self.window.withdraw()
        self.window.title("AutoBard 校准提示")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#010203")
        if os.name == "nt":
            self.window.attributes("-transparentcolor", "#010203")
        self.canvas = Canvas(self.window, bg="#010203", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.last = None

    def show(self, parent, headline, detail):
        state = (parent, headline, detail)
        if state == self.last:
            return
        self.last = state
        width, height = min(720, parent.width), 104
        x, y = parent.left + (parent.width - width) // 2, parent.top + 18
        self.window.geometry(f"{width}x{height}")
        _native_place(self.window, x, y, width, height, passive=True)
        self.canvas.delete("all")
        self.canvas.create_rectangle(10, 6, width - 10, height - 6, fill="#111827", outline="#334155")
        self.canvas.create_text(width // 2, 33, text=headline, fill="#f8fafc",
                                font=("Microsoft YaHei UI", 19, "bold"), width=width - 40)
        self.canvas.create_text(width // 2, 73, text=detail, fill="#cbd5e1",
                                font=("Microsoft YaHei UI", 10), width=width - 40)
        self.window.deiconify()
        _native_place(self.window, x, y, width, height, passive=True)

    def hide(self):
        self.window.withdraw()
        self.last = None

    def destroy(self):
        self.window.destroy()


class SelectionWindow:
    def __init__(self, root, parent, image, headline, detail, on_select=None, buttons=()):
        self.window = Toplevel(root)
        self.window.withdraw()
        self.window.title("AutoBard 画面校准")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.geometry(f"{parent.width}x{parent.height}")
        self.canvas = Canvas(self.window, bg="#0b1220", highlightthickness=0,
                             cursor="crosshair" if on_select else "arrow")
        self.canvas.pack(fill="both", expand=True)
        h, w = image.shape[:2]
        self.viewport = ImageViewport.fit(w, h, parent.width, parent.height)
        v = self.viewport
        resized = cv2.resize(image, (v.width, v.height), interpolation=cv2.INTER_LINEAR)
        encoded = cv2.imencode(".png", resized)[1].tobytes()
        self.photo = PhotoImage(master=self.window, data=base64.b64encode(encoded))
        self.canvas.create_image(v.left, v.top, image=self.photo, anchor="nw")
        self.canvas.create_text(30, 30, anchor="w", text=headline, fill="#f8fafc",
                                font=("Microsoft YaHei UI", 21, "bold"))
        self.canvas.create_text(30, 70, anchor="w", text=detail, fill="#cbd5e1",
                                width=parent.width - 60, font=("Microsoft YaHei UI", 11))
        self.start = self.end = None
        self.on_select = on_select
        self.toolbar = ttk.Frame(self.window)
        self.toolbar.place(relx=0.5, rely=1, anchor="s", y=-16)
        if on_select:
            buttons = (("确认选区 · Enter", self.confirm), *buttons,
                       ("取消 · Esc", lambda: on_select(None)))
            self.canvas.bind("<ButtonPress-1>", self.press)
            self.canvas.bind("<B1-Motion>", self.drag)
            self.canvas.bind("<ButtonRelease-1>", self.drag)
            self.window.bind("<Return>", lambda e: self.confirm())
            self.window.bind("<space>", lambda e: self.confirm())
            self.window.bind("<Escape>", lambda e: on_select(None))
            self.window.bind("<c>", lambda e: on_select(None))
        for label, command in buttons:
            ttk.Button(self.toolbar, text=label, command=command).pack(side="left", padx=5, ipady=5)
        _native_place(self.window, parent.left, parent.top, parent.width, parent.height)
        self.window.deiconify()
        _native_place(self.window, parent.left, parent.top, parent.width, parent.height)
        self.window.after_idle(self.window.focus_force)

    def press(self, event):
        if self.viewport.contains(event.x, event.y):
            self.start = self.end = (event.x, event.y)
            self.drag(event)

    def drag(self, event):
        if self.start is None:
            return
        v = self.viewport
        self.end = (min(v.left + v.width, max(v.left, event.x)),
                    min(v.top + v.height, max(v.top, event.y)))
        self.canvas.delete("selection")
        self.canvas.create_rectangle(*self.start, *self.end, outline="#fbbf24", width=2, tags="selection")

    def confirm(self):
        if self.start is not None and self.end is not None:
            rect = self.viewport.selection(self.start, self.end)
            if rect is not None:
                self.on_select(rect)

    def destroy(self):
        self.window.destroy()


class CalibrationWizard:
    def __init__(self, root, config, output_path, on_finish):
        self.root, self.config, self.output_path, self.on_finish = root, config, output_path, on_finish
        self.hint = CalibrationHint(root)
        self.selector = None
        self.closed = False
        self.phase = "waiting"
        self.deadline = None
        self.parent = None
        self.timers = set()
        self.cancel_event, self.capture_event = threading.Event(), threading.Event()
        self.listener = keyboard.Listener(on_press=self._key)

    def _key(self, key):
        if key == keyboard.Key.esc:
            self.cancel_event.set()
        elif key == keyboard.Key.f8 and self.phase in ("waiting", "countdown"):
            self.capture_event.set()

    def schedule(self, delay, callback):
        def run():
            self.timers.discard(timer)
            if not self.closed:
                try:
                    callback()
                except Exception as exc:
                    self.finish("calibration_error", str(exc))
        timer = self.root.after(delay, run)
        self.timers.add(timer)

    def start(self):
        self.listener.start()
        self.schedule(0, self.poll)

    def poll(self):
        if self.cancel_event.is_set():
            self.finish("calibration_cancelled", None)
            return
        if self.phase in ("waiting", "countdown"):
            parent = foreground_game_rect(str(self.config["window"]["title_contains"]))
            if parent is None:
                self.deadline = None
                self.phase = "waiting"
                self.capture_event.clear()
                monitor = primary_monitor_rect(int(self.config["capture"].get("monitor_index", 1)))
                self.hint.show(monitor, "请切回游戏，让演奏条出现", "无需另行截图 · 游戏在前台后开始倒计时 · Esc 取消")
            else:
                if self.deadline is None or parent != self.parent:
                    self.parent = parent
                    self.deadline = time.monotonic() + int(self.config["calibration"].get("countdown_s", 5))
                self.phase = "countdown"
                remaining = max(0, math.ceil(self.deadline - time.monotonic()))
                self.hint.show(parent, f"{remaining} 秒后截取游戏画面", "请保持演奏条可见 · F8 立即截图 · Esc 取消")
                if remaining == 0 or self.capture_event.is_set():
                    self.capture_event.clear()
                    self.phase = "hiding"
                    self.hint.hide()
                    # Allow the compositor to remove all hint pixels before MSS.
                    self.schedule(180, self.capture)
        self.schedule(100, self.poll)

    def capture(self):
        parent = foreground_game_rect(str(self.config["window"]["title_contains"]))
        if parent is None or parent != self.parent:
            self.phase, self.deadline = "waiting", None
            return
        self.image = _grab(parent)
        self.phase = "selection"
        self.ask_capture()

    def clear_selector(self):
        if self.selector is not None:
            self.selector.destroy()
            self.selector = None

    def guard(self, callback, *args):
        if self.closed:
            return
        try:
            callback(*args)
        except Exception as exc:
            self.finish("calibration_error", str(exc))

    def ask_capture(self):
        self.clear_selector()
        self.selector = SelectionWindow(self.root, self.parent, self.image,
            "第一步：框住完整演奏区域", "这是自动截取的冻结画面。包含整条演奏条和移动指针；拖动框选，Enter 确认，Esc 取消。",
            on_select=lambda rect: self.guard(self.capture_selected, rect),
            buttons=(("重新截图", lambda: self.guard(self.recapture)),))

    def capture_selected(self, rect):
        if rect is None:
            self.finish("calibration_cancelled", None)
            return
        self.capture_local = rect
        self.ask_notes()

    def ask_notes(self, error=""):
        self.clear_selector()
        self.selector = SelectionWindow(self.root, self.parent, self.capture_local.crop(self.image),
            "第二步：紧贴框住音符窄条", error or "画面已放大。只框住金色音符所在的横向窄条，不包含上下文字；Enter 确认，Esc 取消。",
            on_select=lambda rect: self.guard(self.notes_selected, rect),
            buttons=(("返回第一步", lambda: self.guard(self.ask_capture)),
                     ("重新截图", lambda: self.guard(self.recapture))))

    def notes_selected(self, rect):
        if rect is None:
            self.finish("calibration_cancelled", None)
            return
        try:
            self.candidate = prepare_calibration(self.config, self.parent, self.image, self.capture_local, rect)
        except ValueError as exc:
            self.ask_notes(str(exc))
            return
        self.clear_selector()
        self.selector = SelectionWindow(self.root, self.parent, self.candidate.preview,
            f"校准预览 · 识别到 {self.candidate.note_count} 个候选音符",
            "确认蓝框紧贴音符窄条、绿线落在音符上。确认保存后才会替换现有校准。",
            buttons=(("确认保存", self.save), ("重新框选", lambda: self.guard(self.ask_capture)),
                     ("重新截图", lambda: self.guard(self.recapture)), ("取消", lambda: self.finish("calibration_cancelled", None))))
        self.selector.window.bind("<Escape>", lambda e: self.finish("calibration_cancelled", None))

    def recapture(self):
        self.clear_selector()
        self.capture_event.clear()
        self.phase, self.deadline = "waiting", None

    def save(self):
        try:
            save_calibration(self.candidate, self.output_path)
        except Exception as exc:
            self.finish("calibration_error", str(exc))
            return
        self.finish("calibration_done", None)

    def finish(self, kind, value):
        if self.closed:
            return
        self.closed = True
        for timer in self.timers:
            self.root.after_cancel(timer)
        self.timers.clear()
        self.listener.stop()
        self.clear_selector()
        self.hint.destroy()
        self.on_finish(kind, value)
