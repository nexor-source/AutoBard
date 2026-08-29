from __future__ import annotations

from autobard.usbip import (
    SERVICE_RUNNING,
    USBIP_FILTER_SERVICE,
    USBIP_HOST_CONTROLLER_SERVICE,
    detect_usbip_driver,
)


def test_detect_usbip_driver_ready() -> None:
    requested: list[str] = []

    def query(name: str) -> int:
        requested.append(name)
        return SERVICE_RUNNING

    status = detect_usbip_driver(query=query, platform_name="nt")

    assert status.installed
    assert status.running
    assert status.filter_running
    assert status.level == "ready"
    assert requested == [USBIP_HOST_CONTROLLER_SERVICE, USBIP_FILTER_SERVICE]


def test_detect_usbip_driver_missing() -> None:
    status = detect_usbip_driver(query=lambda _name: None, platform_name="nt")

    assert not status.installed
    assert status.level == "missing"
    assert "usbip2_ude" in status.display_text()


def test_detect_usbip_driver_installed_but_stopped() -> None:
    status = detect_usbip_driver(query=lambda _name: 1, platform_name="nt")

    assert status.installed
    assert not status.running
    assert status.filter_installed
    assert status.level == "warning"
    assert "已安装但当前未运行" in status.display_text()


def test_detect_usbip_driver_reports_query_error() -> None:
    def query(_name: str) -> int | None:
        raise OSError("access denied")

    status = detect_usbip_driver(query=query, platform_name="nt")

    assert status.error == "access denied"
    assert status.level == "error"


def test_detect_usbip_driver_is_windows_only() -> None:
    called = False

    def query(_name: str) -> int | None:
        nonlocal called
        called = True
        return SERVICE_RUNNING

    status = detect_usbip_driver(query=query, platform_name="posix")

    assert not status.supported
    assert status.level == "missing"
    assert not called
