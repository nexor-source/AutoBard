from __future__ import annotations

import json
import logging
import os
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from autobard.models import Note

from .base import ActionSink

LOGGER = logging.getLogger("autobard.action")

MOUSE_BUTTON_RIGHT = 0x02
_MOUSE_REPORT = struct.Struct("<Bhhhh")


class ViiperAction(ActionSink):
    """Send right-button reports through a VIIPER USB/IP virtual mouse."""

    def __init__(
        self,
        kind: str,
        press_duration_ms: int,
        executable: str = "runtime/viiper.exe",
        host: str = "127.0.0.1",
        api_port: int = 3242,
        usb_port: int = 3241,
        startup_timeout_s: float = 10.0,
    ) -> None:
        if kind.casefold() != "mouse_right":
            raise ValueError("VIIPER currently supports action.kind=mouse_right only")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("This VIIPER backend only supports a local server")

        self.duration = max(0.0, press_duration_ms / 1000.0)
        self.executable = self._resolve_executable(executable)
        self.host = host
        self.api_port = int(api_port)
        self.usb_port = int(usb_port)
        self.startup_timeout_s = max(0.5, float(startup_timeout_s))
        self._process: subprocess.Popen[bytes] | None = None
        self._owns_process = False
        self._bus_id: int | None = None
        self._device_id: str | None = None
        self._stream: socket.socket | None = None
        self._lock = threading.Lock()
        self._closed = False

        try:
            self._ensure_server()
            bus = self._request("bus/create")
            self._bus_id = int(bus["busId"])
            device = self._request(f'bus/{self._bus_id}/add {{"type":"mouse"}}')
            self._device_id = str(device["devId"])
            self._stream = socket.create_connection(
                (self.host, self.api_port), timeout=self.startup_timeout_s
            )
            self._stream.sendall(f"bus/{self._bus_id}/{self._device_id}\0".encode("ascii"))
            self._stream.settimeout(None)
            LOGGER.info(
                "VIIPER USB/IP mouse ready bus=%d device=%s",
                self._bus_id,
                self._device_id,
            )
        except Exception:
            self.close()
            raise

    @staticmethod
    def _resolve_executable(value: str) -> Path:
        configured = Path(value).expanduser()
        candidates = [configured]
        if not configured.is_absolute():
            project_root = Path(__file__).resolve().parents[3]
            candidates = [Path.cwd() / configured, project_root / configured]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return candidates[0].resolve()

    def _request(self, command: str) -> dict[str, Any]:
        chunks: list[bytes] = []
        with socket.create_connection(
            (self.host, self.api_port), timeout=self.startup_timeout_s
        ) as connection:
            connection.sendall(command.encode("utf-8") + b"\0")
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)

        raw = b"".join(chunks).decode("utf-8").strip()
        if not raw:
            return {}
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid response from VIIPER: {raw!r}") from exc
        if not isinstance(response, dict):
            raise RuntimeError(f"Unexpected response from VIIPER: {response!r}")
        if int(response.get("status", 0)) >= 400:
            detail = response.get("detail") or response.get("title") or raw
            raise RuntimeError(f"VIIPER API error: {detail}")
        return response

    def _ping(self) -> None:
        response = self._request("ping")
        if response.get("server") != "VIIPER":
            raise RuntimeError(f"Port {self.api_port} is not a VIIPER API server")

    def _ensure_server(self) -> None:
        try:
            self._ping()
            LOGGER.info("Using existing VIIPER server at %s:%d", self.host, self.api_port)
            return
        except OSError:
            pass

        if not self.executable.is_file():
            raise FileNotFoundError(f"VIIPER executable not found: {self.executable}")

        log_path = self.executable.with_name("viiper.log")
        command = [
            str(self.executable),
            "server",
            f"--usb.addr=127.0.0.1:{self.usb_port}",
            f"--api.addr=127.0.0.1:{self.api_port}",
            "--api.auto-attach-local-client",
            "--api.auto-attach-windows-native",
            f"--log.file={log_path}",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._owns_process = True

        deadline = time.monotonic() + self.startup_timeout_s
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"VIIPER exited during startup (code {self._process.returncode}); "
                    f"see {log_path}"
                )
            try:
                self._ping()
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.05)
        raise TimeoutError(
            f"VIIPER did not become ready within {self.startup_timeout_s:g}s: {last_error}"
        )

    def _send_mouse_state(self, buttons: int) -> None:
        if self._stream is None:
            raise RuntimeError("VIIPER mouse stream is not connected")
        self._stream.sendall(_MOUSE_REPORT.pack(buttons, 0, 0, 0, 0))

    def hit_note(self, note: Note, timestamp: float) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("VIIPER action is closed")
            self._send_mouse_state(MOUSE_BUTTON_RIGHT)
            if self.duration:
                time.sleep(self.duration)
            self._send_mouse_state(0)
        LOGGER.info(
            "VIIPER mouse_right note=%d target=%.1f duration_ms=%.0f t=%.6f",
            note.index,
            note.target,
            self.duration * 1000,
            timestamp,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._stream is not None:
                try:
                    self._send_mouse_state(0)
                except OSError:
                    LOGGER.debug("Could not send final neutral VIIPER report", exc_info=True)
                try:
                    self._stream.close()
                finally:
                    self._stream = None

        if self._bus_id is not None and self._device_id is not None:
            try:
                self._request(f"bus/{self._bus_id}/remove {self._device_id}")
            except (OSError, RuntimeError):
                LOGGER.debug("Could not remove VIIPER mouse device", exc_info=True)
            self._device_id = None
        if self._bus_id is not None:
            try:
                self._request(f"bus/remove {self._bus_id}")
            except (OSError, RuntimeError):
                LOGGER.debug("Could not remove VIIPER bus", exc_info=True)
            self._bus_id = None

        if self._owns_process and self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
            self._process = None
            self._owns_process = False
