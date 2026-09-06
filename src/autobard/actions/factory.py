from __future__ import annotations

from .base import ActionSink
from .beep import BeepAction
from .dry_run import DryRunAction


def create_action_sink(config: dict) -> ActionSink:
    mode = str(config.get("mode", "dry_run")).casefold()
    if mode == "dry_run":
        return DryRunAction()
    if mode == "beep":
        return BeepAction()
    if mode == "system_input":
        if not bool(config.get("acknowledge_online_risk", False)):
            raise RuntimeError(
                "system_input is locked. Set action.acknowledge_online_risk=true only after "
                "you understand the game's rules and account risk."
            )
        mouse_backend = str(config.get("mouse_backend", "viiper")).casefold()
        if mouse_backend == "viiper":
            from .viiper import ViiperAction

            viiper = config.get("viiper", {})
            if not isinstance(viiper, dict):
                raise ValueError("action.viiper must be an object")
            return ViiperAction(
                kind=str(config.get("kind", "mouse_right")),
                press_duration_ms=int(config.get("press_duration_ms", 20)),
                executable=str(viiper.get("executable", "runtime/viiper.exe")),
                host=str(viiper.get("host", "127.0.0.1")),
                api_port=int(viiper.get("api_port", 3242)),
                usb_port=int(viiper.get("usb_port", 3241)),
                startup_timeout_s=float(viiper.get("startup_timeout_s", 10.0)),
            )

        from .send_input import SendInputAction

        return SendInputAction(
            kind=str(config.get("kind", "mouse_right")),
            key=str(config.get("key", "space")),
            press_duration_ms=int(config.get("press_duration_ms", 20)),
            mouse_backend=mouse_backend,
        )
    raise ValueError(f"Unsupported action mode: {mode}")
