from __future__ import annotations

import copy
import logging
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, messagebox
from tkinter import scrolledtext, ttk

from . import __version__
from .calibration import CalibrationCancelled, calibrate, calibration_instructions
from .config import load_config, save_config, validate_config
from .service import HotkeyService
from .usbip import UsbIpDriverStatus, detect_usbip_driver
from .updater import (
    GitHubUpdater,
    PreparedUpdate,
    UpdateError,
    UpdateInfo,
    application_directory,
    launch_windows_installer,
)


LOGGER = logging.getLogger(__name__)


class _GuiLogHandler(logging.Handler):
    def __init__(self, messages: queue.Queue[tuple[str, object]]) -> None:
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.put(("log", self.format(record)))
        except Exception:
            self.handleError(record)


class AutoBardGui:
    def __init__(self, root: Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path.resolve()
        self.app_dir = application_directory()
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.service: HotkeyService | None = None
        self.service_thread: threading.Thread | None = None
        self.calibration_thread: threading.Thread | None = None
        self.calibration_in_progress = False
        self.calibration_after_id: str | None = None
        self.update_thread: threading.Thread | None = None
        self.usbip_check_thread: threading.Thread | None = None
        self.usbip_driver_status: UsbIpDriverStatus | None = None
        self.pending_update: PreparedUpdate | None = None
        self.closing = False

        self.config = load_config(self.config_path)
        self._create_variables()
        self._configure_window()
        self._install_logging()
        self._build_ui()
        self._refresh_buttons()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll)
        self.root.after(250, lambda: self.check_usbip_driver(manual=False))

        updates = self.config.get("updates", {})
        if bool(updates.get("enabled", True)) and bool(updates.get("check_on_start", True)):
            self.root.after(1200, lambda: self.check_for_updates(manual=False))

    def _create_variables(self) -> None:
        capture = self.config["capture"]
        action = self.config["action"]
        hotkeys = self.config["hotkeys"]
        debug = self.config["debug"]
        session = self.config["session"]
        calibration = self.config.get("calibration", {})
        updates = self.config.get("updates", {})
        self.status_text = StringVar(value="已停止")
        self.usbip_status_text = StringVar(value="正在等待检测…")
        self.capture_backend = StringVar(value=str(capture.get("backend", "mss")))
        self.target_fps = IntVar(value=int(capture.get("target_fps", 120)))
        self.action_mode = StringVar(value=str(action.get("mode", "dry_run")))
        self.press_duration = IntVar(value=int(action.get("press_duration_ms", 10)))
        self.risk_acknowledged = BooleanVar(
            value=bool(action.get("acknowledge_online_risk", False))
        )
        self.double_click_interval = IntVar(
            value=int(hotkeys.get("double_right_click_interval_ms", 350))
        )
        self.calibration_countdown = IntVar(
            value=int(calibration.get("countdown_s", 5))
        )
        self.pointer_start_delay = IntVar(
            value=int(session.get("pointer_start_delay_ms", 0))
        )
        self.debug_enabled = BooleanVar(value=bool(debug.get("enabled", True)))
        self.update_enabled = BooleanVar(value=bool(updates.get("enabled", True)))
        self.update_on_start = BooleanVar(value=bool(updates.get("check_on_start", True)))
        self.github_repo = StringVar(
            value=str(updates.get("github_repo", "nexor-source/AutoBard"))
        )

    def _configure_window(self) -> None:
        self.root.title(f"AutoBard {__version__}")
        self.root.geometry("820x680")
        self.root.minsize(740, 600)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Subheader.TLabel", foreground="#555555")
        style.configure("Primary.TButton", padding=(14, 8))
        style.configure("Danger.TButton", padding=(14, 8))

    def _install_logging(self) -> None:
        handler = _GuiLogHandler(self.messages)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        )
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        self.log_handler = handler

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x")
        ttk.Label(header, text="AutoBard", style="Header.TLabel").pack(side="left")
        ttk.Label(
            header,
            text=f"v{__version__} · VIIPER / USB-IP",
            style="Subheader.TLabel",
        ).pack(side="left", padx=(12, 0), pady=(8, 0))
        self.status_label = ttk.Label(header, textvariable=self.status_text)
        self.status_label.pack(side="right", pady=(8, 0))

        controls = ttk.LabelFrame(container, text="运行控制", padding=12)
        controls.pack(fill="x", pady=(14, 10))
        self.start_button = ttk.Button(
            controls, text="启动服务", style="Primary.TButton", command=self.start_service
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            controls, text="停止服务", style="Danger.TButton", command=self.stop_service
        )
        self.stop_button.pack(side="left", padx=8)
        self.trigger_button = ttk.Button(
            controls, text="立即检测一次", command=self.trigger_session
        )
        self.trigger_button.pack(side="left", padx=(14, 4))
        self.abort_button = ttk.Button(
            controls, text="中止当前检测", command=self.abort_session
        )
        self.abort_button.pack(side="left", padx=4)
        ttk.Label(
            controls,
            text="双击右键开始 · F9 中止 · F10 停止服务",
            style="Subheader.TLabel",
        ).pack(side="right")

        notebook = ttk.Notebook(container)
        notebook.pack(fill="x", pady=(0, 10))
        basic_tab = ttk.Frame(notebook, padding=14)
        update_tab = ttk.Frame(notebook, padding=14)
        notebook.add(basic_tab, text="基本设置")
        notebook.add(update_tab, text="更新与维护")
        self._build_basic_settings(basic_tab)
        self._build_update_settings(update_tab)

        log_frame = ttk.LabelFrame(container, text="运行日志", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=12,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            background="#101418",
            foreground="#d8e2ea",
            insertbackground="#ffffff",
        )
        self.log_text.pack(fill="both", expand=True)
        self._append_log(f"AutoBard GUI {__version__} 已就绪。配置：{self.config_path}")

    def _build_basic_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="捕获后端").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.capture_backend,
            values=("mss", "auto", "dxcam"),
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=(8, 24), pady=4)
        ttk.Label(parent, text="目标 FPS").grid(row=0, column=2, sticky="w", pady=4)
        ttk.Spinbox(parent, from_=30, to=240, textvariable=self.target_fps, width=8).grid(
            row=0, column=3, sticky="w", padx=8, pady=4
        )

        ttk.Label(parent, text="输出模式").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.action_mode,
            values=("system_input", "dry_run", "beep"),
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", padx=(8, 24), pady=4)
        ttk.Label(parent, text="右键保持时间 (ms)").grid(row=1, column=2, sticky="w", pady=4)
        ttk.Spinbox(parent, from_=0, to=200, textvariable=self.press_duration, width=8).grid(
            row=1, column=3, sticky="w", padx=8, pady=4
        )

        ttk.Label(parent, text="双击间隔 (ms)").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Spinbox(
            parent, from_=100, to=1000, textvariable=self.double_click_interval, width=12
        ).grid(row=2, column=1, sticky="w", padx=(8, 24), pady=4)
        ttk.Checkbutton(parent, text="保存调试数据", variable=self.debug_enabled).grid(
            row=2, column=2, sticky="w", pady=4
        )
        ttk.Checkbutton(
            parent,
            text="我了解在线游戏自动化可能带来的账号风险",
            variable=self.risk_acknowledged,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 4))

        ttk.Separator(parent).grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=(10, 8)
        )
        ttk.Label(parent, text="USB/IP 驱动").grid(row=5, column=0, sticky="nw", pady=4)
        self.usbip_status_label = ttk.Label(
            parent,
            textvariable=self.usbip_status_text,
            wraplength=430,
        )
        self.usbip_status_label.grid(
            row=5, column=1, columnspan=2, sticky="w", padx=(8, 12), pady=4
        )
        usbip_actions = ttk.Frame(parent)
        usbip_actions.grid(row=5, column=3, sticky="e", pady=4)
        self.usbip_check_button = ttk.Button(
            usbip_actions,
            text="重新检测",
            command=lambda: self.check_usbip_driver(manual=True),
        )
        self.usbip_check_button.pack(side="left")
        ttk.Button(
            usbip_actions,
            text="安装说明",
            command=self.open_usbip_instructions,
        ).pack(side="left", padx=(6, 0))

        ttk.Label(parent, text="校准准备时间 (秒)").grid(
            row=6, column=0, sticky="w", pady=(8, 4)
        )
        ttk.Spinbox(
            parent,
            from_=0,
            to=60,
            textvariable=self.calibration_countdown,
            width=12,
        ).grid(row=6, column=1, sticky="w", padx=(8, 24), pady=(8, 4))
        ttk.Label(parent, text="额外启动延迟 (ms)").grid(
            row=6, column=2, sticky="w", pady=(8, 4)
        )
        ttk.Spinbox(
            parent,
            from_=0,
            to=2000,
            increment=25,
            textvariable=self.pointer_start_delay,
            width=10,
        ).grid(row=6, column=3, sticky="w", padx=8, pady=(8, 4))
        ttk.Label(
            parent,
            text=(
                "指针会自动等待连续向右运动后再锁定；额外延迟通常保持 0，"
                "仅用于规避特殊界面动画"
            ),
            style="Subheader.TLabel",
            wraplength=690,
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(2, 4))

        actions = ttk.Frame(parent)
        actions.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="保存设置", command=self.save_settings).pack(side="left")
        self.calibrate_button = ttk.Button(
            actions, text="重新校准画面", command=self.run_calibration
        )
        self.calibrate_button.pack(side="left", padx=8)
        ttk.Button(actions, text="打开调试目录", command=self.open_debug_directory).pack(
            side="left"
        )
        parent.columnconfigure(3, weight=1)

    def _build_update_settings(self, parent: ttk.Frame) -> None:
        ttk.Checkbutton(parent, text="启用更新功能", variable=self.update_enabled).grid(
            row=0, column=0, sticky="w", pady=4
        )
        ttk.Checkbutton(parent, text="启动时自动检查", variable=self.update_on_start).grid(
            row=0, column=1, sticky="w", padx=20, pady=4
        )
        ttk.Label(parent, text="GitHub 仓库").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(parent, textvariable=self.github_repo, width=38).grid(
            row=1, column=1, sticky="ew", padx=(20, 8), pady=8
        )
        self.update_button = ttk.Button(
            parent, text="立即检查更新", command=lambda: self.check_for_updates(manual=True)
        )
        self.update_button.grid(row=1, column=2, sticky="e", pady=8)
        ttk.Label(
            parent,
            text=(
                "更新来自 GitHub Releases，要求同时发布 AutoBard-win64.zip 和 "
                "AutoBard-win64.zip.sha256。安装时不会覆盖本机 config 与 debug_output。"
            ),
            wraplength=690,
            style="Subheader.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        parent.columnconfigure(1, weight=1)

    def _apply_variables(self) -> dict:
        config = copy.deepcopy(self.config)
        config["capture"]["backend"] = self.capture_backend.get().strip()
        config["capture"]["target_fps"] = max(1, int(self.target_fps.get()))
        config["action"]["mode"] = self.action_mode.get().strip()
        config["action"]["press_duration_ms"] = max(0, int(self.press_duration.get()))
        config["action"]["acknowledge_online_risk"] = bool(
            self.risk_acknowledged.get()
        )
        config["hotkeys"]["double_right_click_interval_ms"] = max(
            50, int(self.double_click_interval.get())
        )
        calibration = config.setdefault("calibration", {})
        calibration["countdown_s"] = max(
            0, min(60, int(self.calibration_countdown.get()))
        )
        config["session"]["pointer_start_delay_ms"] = max(
            0, min(2000, int(self.pointer_start_delay.get()))
        )
        config["debug"]["enabled"] = bool(self.debug_enabled.get())
        updates = config.setdefault("updates", {})
        updates["enabled"] = bool(self.update_enabled.get())
        updates["check_on_start"] = bool(self.update_on_start.get())
        updates["github_repo"] = self.github_repo.get().strip()
        updates.setdefault("asset_name", "AutoBard-win64.zip")
        updates.setdefault("timeout_s", 15.0)
        validate_config(config)
        return config

    def save_settings(self, quiet: bool = False) -> bool:
        if self._service_is_alive():
            if not quiet:
                messagebox.showwarning("服务正在运行", "请先停止服务，再修改设置。")
            return False
        try:
            config = self._apply_variables()
            save_config(config, self.config_path)
            self.config = config
            self._append_log("设置已保存。")
            if not quiet:
                messagebox.showinfo("AutoBard", "设置已保存。")
            return True
        except Exception as exc:
            messagebox.showerror("设置保存失败", str(exc))
            return False

    def start_service(self) -> None:
        if self.calibration_in_progress:
            messagebox.showwarning("正在校准", "请先完成或取消当前画面校准。")
            return
        if self._service_is_alive() or not self.save_settings(quiet=True):
            return
        if self.action_mode.get() == "system_input" and not self.risk_acknowledged.get():
            messagebox.showwarning("需要风险确认", "使用 system_input 前必须勾选风险确认。")
            return
        action = self.config.get("action", {})
        uses_viiper = (
            self.action_mode.get() == "system_input"
            and str(action.get("mouse_backend", "viiper")).casefold() == "viiper"
        )
        if uses_viiper:
            driver_status = detect_usbip_driver()
            self._apply_usbip_status(driver_status, manual=False)
            if not driver_status.supported:
                messagebox.showerror("USB/IP 不可用", driver_status.display_text())
                return
            if driver_status.error:
                if not messagebox.askyesno(
                    "无法确认 USB/IP 驱动",
                    f"{driver_status.display_text()}\n\n是否仍然尝试启动 VIIPER？",
                ):
                    return
            elif not driver_status.installed:
                messagebox.showerror(
                    "缺少 USB/IP 驱动",
                    "未检测到 usbip-win2 的 usbip2_ude 驱动。\n\n"
                    "请点击“安装说明”安装驱动，然后重新检测。",
                )
                return
        self.service = HotkeyService(copy.deepcopy(self.config))
        self.status_text.set("正在启动…")
        self.service_thread = threading.Thread(
            target=self._service_worker,
            name="autobard-service",
            daemon=False,
        )
        self.service_thread.start()
        self._refresh_buttons()

    def _service_worker(self) -> None:
        assert self.service is not None
        try:
            self.service.run()
        except Exception as exc:
            LOGGER.exception("服务启动或运行失败")
            self.messages.put(("service_error", str(exc)))
        finally:
            self.messages.put(("service_stopped", None))

    def stop_service(self) -> None:
        if self.service is not None:
            self.status_text.set("正在停止…")
            self.service.stop()
            self._refresh_buttons()

    def trigger_session(self) -> None:
        if self.service is None or not self.service.ready_event.is_set():
            messagebox.showwarning("服务未启动", "请先启动服务。")
            return
        self.service.request_session()
        self._append_log("已请求立即开始一次检测。")

    def abort_session(self) -> None:
        if self.service is not None:
            self.service.abort_session()
            self._append_log("已请求中止当前检测。")

    def run_calibration(self) -> None:
        if self.calibration_in_progress:
            return
        if self._service_is_alive():
            messagebox.showwarning("服务正在运行", "请先停止服务，再进行校准。")
            return
        if not self.save_settings(quiet=True):
            return
        countdown_s = int(self.calibration_countdown.get())
        if not messagebox.askokcancel(
            "重新校准画面",
            calibration_instructions(countdown_s),
            icon="info",
        ):
            return
        self.calibration_in_progress = True
        self._refresh_buttons()
        self.root.iconify()
        self._append_log(
            f"校准准备开始：GUI 已最小化，{countdown_s} 秒后截图。"
        )
        self._calibration_countdown_tick(countdown_s)

    def _calibration_countdown_tick(self, remaining: int) -> None:
        if self.closing or not self.calibration_in_progress:
            return
        if remaining > 0:
            self.status_text.set(f"校准将在 {remaining} 秒后截图…")
            self.calibration_after_id = self.root.after(
                1000,
                lambda: self._calibration_countdown_tick(remaining - 1),
            )
            return

        self.calibration_after_id = None
        self.status_text.set("正在截图并等待框选…")
        self.calibration_thread = threading.Thread(
            target=self._calibration_worker,
            name="autobard-calibration",
            daemon=True,
        )
        self.calibration_thread.start()

    def _calibration_worker(self) -> None:
        try:
            calibrate(copy.deepcopy(self.config), str(self.config_path))
            self.messages.put(("calibration_done", None))
        except CalibrationCancelled:
            self.messages.put(("calibration_cancelled", None))
        except Exception as exc:
            LOGGER.exception("校准失败")
            self.messages.put(("calibration_error", str(exc)))

    def _restore_after_calibration(self) -> None:
        self.calibration_in_progress = False
        self.calibration_after_id = None
        self.root.deiconify()
        self.root.lift()
        self._refresh_buttons()

    def open_debug_directory(self) -> None:
        path = Path(str(self.config["debug"].get("output_dir", "debug_output")))
        if not path.is_absolute():
            path = self.app_dir / path
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    def open_usbip_instructions(self) -> None:
        webbrowser.open("https://github.com/vadimgrn/usbip-win2")

    def check_usbip_driver(self, manual: bool) -> None:
        if self.usbip_check_thread is not None and self.usbip_check_thread.is_alive():
            return
        self.usbip_status_text.set("正在检测 usbip-win2…")
        self.usbip_status_label.configure(foreground="#555555")
        self.usbip_check_button.configure(state="disabled")
        self.usbip_check_thread = threading.Thread(
            target=self._usbip_check_worker,
            args=(manual,),
            name="autobard-usbip-check",
            daemon=True,
        )
        self.usbip_check_thread.start()

    def _usbip_check_worker(self, manual: bool) -> None:
        self.messages.put(("usbip_status", (detect_usbip_driver(), manual)))

    def _apply_usbip_status(
        self,
        status: UsbIpDriverStatus,
        manual: bool,
    ) -> None:
        self.usbip_driver_status = status
        self.usbip_status_text.set(status.display_text())
        colors = {
            "ready": "#16803c",
            "warning": "#a15c00",
            "missing": "#b00020",
            "error": "#b00020",
        }
        self.usbip_status_label.configure(foreground=colors[status.level])
        self.usbip_check_button.configure(state="normal")
        prefix = "USB/IP 驱动检测"
        self._append_log(f"{prefix}：{status.display_text()}")
        if manual and status.level == "ready":
            messagebox.showinfo("USB/IP 驱动", status.display_text())

    def check_for_updates(self, manual: bool) -> None:
        if self.update_thread is not None and self.update_thread.is_alive():
            return
        try:
            if not self.save_settings(quiet=True) and not self._service_is_alive():
                return
        except Exception:
            return
        updates = copy.deepcopy(self.config.get("updates", {}))
        if not bool(updates.get("enabled", True)) and not manual:
            return
        self.update_button.configure(state="disabled")
        self._append_log("正在检查更新…")
        self.update_thread = threading.Thread(
            target=self._update_check_worker,
            args=(updates, manual),
            daemon=True,
        )
        self.update_thread.start()

    def _update_check_worker(self, updates: dict, manual: bool) -> None:
        try:
            updater = GitHubUpdater(
                repository=str(updates.get("github_repo", "nexor-source/AutoBard")),
                current_version=__version__,
                asset_name=str(updates.get("asset_name", "AutoBard-win64.zip")),
                timeout_s=float(updates.get("timeout_s", 15.0)),
            )
            result = updater.check()
            self.messages.put(("update_result", (updater, result, manual)))
        except Exception as exc:
            self.messages.put(("update_error", (str(exc), manual)))

    def _handle_update_result(
        self,
        updater: GitHubUpdater,
        update: UpdateInfo | None,
        manual: bool,
    ) -> None:
        self.update_button.configure(state="normal")
        if update is None:
            self._append_log("当前已经是最新版本。")
            if manual:
                messagebox.showinfo("检查更新", "当前已经是最新版本。")
            return
        notes = update.notes.strip() or "此版本没有提供更新说明。"
        notes_preview = notes[:900] + ("…" if len(notes) > 900 else "")
        if not getattr(sys, "frozen", False):
            self._append_log(f"发现新版本 {update.version}（源码运行模式不自动安装）。")
            if messagebox.askyesno(
                "发现新版本",
                f"发现 AutoBard {update.version}。\n\n{notes_preview}\n\n是否打开发布页面？",
            ):
                webbrowser.open(update.page_url)
            return
        if not messagebox.askyesno(
            "发现新版本",
            f"发现 AutoBard {update.version}。\n\n{notes_preview}\n\n是否下载并安装？",
        ):
            return
        self.update_button.configure(state="disabled")
        self.status_text.set(f"正在下载 {update.version}…")
        self.update_thread = threading.Thread(
            target=self._update_download_worker,
            args=(updater, update),
            daemon=True,
        )
        self.update_thread.start()

    def _update_download_worker(self, updater: GitHubUpdater, update: UpdateInfo) -> None:
        try:
            prepared = updater.prepare(
                update,
                progress=lambda current, total: self.messages.put(
                    ("update_progress", (current, total))
                ),
            )
            self.messages.put(("update_prepared", prepared))
        except Exception as exc:
            self.messages.put(("update_error", (str(exc), True)))

    def _begin_install(self, prepared: PreparedUpdate) -> None:
        self.pending_update = prepared
        self.status_text.set("正在准备安装更新…")
        if self.service is not None:
            self.service.stop()
        self.root.after(100, self._finish_install_when_ready)

    def _finish_install_when_ready(self) -> None:
        if self._service_is_alive():
            self.root.after(100, self._finish_install_when_ready)
            return
        assert self.pending_update is not None
        try:
            launch_windows_installer(self.pending_update, self.app_dir)
        except UpdateError as exc:
            self.status_text.set("更新安装失败")
            self.update_button.configure(state="normal")
            messagebox.showerror("更新安装失败", str(exc))
            return
        self.closing = True
        self.root.destroy()

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    self._append_log(str(value))
                elif kind == "service_error":
                    messagebox.showerror("AutoBard 服务错误", str(value))
                elif kind == "service_stopped":
                    self.status_text.set("已停止")
                    self._refresh_buttons()
                elif kind == "calibration_done":
                    self.config = load_config(self.config_path)
                    self._restore_after_calibration()
                    self.status_text.set("已停止")
                    self._append_log("校准完成，配置已重新载入。")
                    messagebox.showinfo("校准完成", "画面区域已经保存。")
                elif kind == "calibration_cancelled":
                    self._restore_after_calibration()
                    self.status_text.set("已停止")
                    self._append_log("用户取消了画面校准。")
                    messagebox.showinfo("校准已取消", "没有修改现有校准设置。")
                elif kind == "calibration_error":
                    self._restore_after_calibration()
                    self.status_text.set("已停止")
                    messagebox.showerror("校准失败", str(value))
                elif kind == "usbip_status":
                    usbip_status, manual = value  # type: ignore[misc]
                    self._apply_usbip_status(usbip_status, manual)
                elif kind == "update_result":
                    updater, update, manual = value  # type: ignore[misc]
                    self._handle_update_result(updater, update, manual)
                elif kind == "update_error":
                    error, manual = value  # type: ignore[misc]
                    self.update_button.configure(state="normal")
                    self.status_text.set("运行中" if self._service_is_ready() else "已停止")
                    self._append_log(f"更新检查失败：{error}")
                    if manual:
                        messagebox.showerror("更新失败", str(error))
                elif kind == "update_progress":
                    current, total = value  # type: ignore[misc]
                    if total:
                        self.status_text.set(f"正在下载更新… {current * 100 // total}%")
                    else:
                        self.status_text.set(f"正在下载更新… {current // 1024} KiB")
                elif kind == "update_prepared":
                    self._begin_install(value)  # type: ignore[arg-type]
        except queue.Empty:
            pass

        if self.service is not None and self.service.ready_event.is_set():
            if not self.status_text.get().startswith("正在下载"):
                self.status_text.set("运行中 · 等待双击右键")
            self._refresh_buttons()
        if not self.closing:
            self.root.after(100, self._poll)

    def _service_is_alive(self) -> bool:
        return self.service_thread is not None and self.service_thread.is_alive()

    def _service_is_ready(self) -> bool:
        return self.service is not None and self.service.ready_event.is_set()

    def _refresh_buttons(self) -> None:
        alive = self._service_is_alive()
        ready = self._service_is_ready()
        busy = alive or self.calibration_in_progress
        self.start_button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if alive else "disabled")
        self.trigger_button.configure(state="normal" if ready else "disabled")
        self.abort_button.configure(state="normal" if ready else "disabled")
        self.calibrate_button.configure(state="disabled" if busy else "normal")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.service is not None:
            self.service.stop()
        self._wait_then_close()

    def _wait_then_close(self) -> None:
        if self._service_is_alive():
            self.root.after(100, self._wait_then_close)
            return
        logging.getLogger().removeHandler(self.log_handler)
        self.root.destroy()


def main(config_path: str | Path | None = None) -> int:
    app_dir = application_directory()
    os.chdir(app_dir)
    selected = Path(config_path) if config_path else app_dir / "config" / "settings.json"
    root = Tk()
    try:
        AutoBardGui(root, selected)
    except Exception as exc:
        messagebox.showerror("AutoBard 启动失败", str(exc), parent=root)
        root.destroy()
        return 1
    root.mainloop()
    return 0
