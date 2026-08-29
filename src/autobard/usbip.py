from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass


USBIP_HOST_CONTROLLER_SERVICE = "usbip2_ude"
USBIP_FILTER_SERVICE = "usbip2_filter"
SERVICE_RUNNING = 4
ERROR_SERVICE_DOES_NOT_EXIST = 1060


@dataclass(frozen=True, slots=True)
class UsbIpDriverStatus:
    supported: bool
    host_controller_state: int | None = None
    filter_state: int | None = None
    error: str | None = None

    @property
    def installed(self) -> bool:
        return self.supported and self.host_controller_state is not None

    @property
    def running(self) -> bool:
        return self.host_controller_state == SERVICE_RUNNING

    @property
    def filter_installed(self) -> bool:
        return self.filter_state is not None

    @property
    def filter_running(self) -> bool:
        return self.filter_state == SERVICE_RUNNING

    @property
    def level(self) -> str:
        if self.error:
            return "error"
        if not self.supported or not self.installed:
            return "missing"
        if self.running and self.filter_running:
            return "ready"
        return "warning"

    def display_text(self) -> str:
        if not self.supported:
            return "仅支持在 Windows 上检测 USB/IP 驱动"
        if self.error:
            return f"检测失败：{self.error}"
        if not self.installed:
            return "未安装 usbip-win2（缺少 usbip2_ude）"
        if self.running and self.filter_running:
            return "已安装并运行（usbip2_ude / usbip2_filter）"
        if self.running and not self.filter_installed:
            return "主驱动正在运行，但未检测到 usbip2_filter"
        if self.running:
            return "主驱动正在运行，usbip2_filter 当前未运行"
        if self.filter_installed:
            return "驱动已安装但当前未运行；启动 VIIPER 时将再次验证"
        return "主驱动已安装但当前未运行，且缺少 usbip2_filter"


def _query_windows_driver_state(service_name: str) -> int | None:
    class ServiceStatusProcess(ctypes.Structure):
        _fields_ = [
            ("dwServiceType", wintypes.DWORD),
            ("dwCurrentState", wintypes.DWORD),
            ("dwControlsAccepted", wintypes.DWORD),
            ("dwWin32ExitCode", wintypes.DWORD),
            ("dwServiceSpecificExitCode", wintypes.DWORD),
            ("dwCheckPoint", wintypes.DWORD),
            ("dwWaitHint", wintypes.DWORD),
            ("dwProcessId", wintypes.DWORD),
            ("dwServiceFlags", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.QueryServiceStatusEx.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        ctypes.POINTER(wintypes.BYTE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
    advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    advapi32.CloseServiceHandle.restype = wintypes.BOOL

    sc_manager_connect = 0x0001
    service_query_status = 0x0004
    sc_status_process_info = 0

    manager = advapi32.OpenSCManagerW(None, None, sc_manager_connect)
    if not manager:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        service = advapi32.OpenServiceW(manager, service_name, service_query_status)
        if not service:
            error_code = ctypes.get_last_error()
            if error_code == ERROR_SERVICE_DOES_NOT_EXIST:
                return None
            raise ctypes.WinError(error_code)
        try:
            status = ServiceStatusProcess()
            bytes_needed = wintypes.DWORD()
            ok = advapi32.QueryServiceStatusEx(
                service,
                sc_status_process_info,
                ctypes.cast(ctypes.byref(status), ctypes.POINTER(wintypes.BYTE)),
                ctypes.sizeof(status),
                ctypes.byref(bytes_needed),
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            return int(status.dwCurrentState)
        finally:
            advapi32.CloseServiceHandle(service)
    finally:
        advapi32.CloseServiceHandle(manager)


def detect_usbip_driver(
    query: Callable[[str], int | None] | None = None,
    platform_name: str | None = None,
) -> UsbIpDriverStatus:
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != "nt":
        return UsbIpDriverStatus(supported=False)

    query = _query_windows_driver_state if query is None else query
    try:
        host_state = query(USBIP_HOST_CONTROLLER_SERVICE)
        filter_state = query(USBIP_FILTER_SERVICE)
    except OSError as exc:
        return UsbIpDriverStatus(supported=True, error=str(exc))

    return UsbIpDriverStatus(
        supported=True,
        host_controller_state=host_state,
        filter_state=filter_state,
    )
