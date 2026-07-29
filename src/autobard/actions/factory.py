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
        from .send_input import SendInputAction

        return SendInputAction(
            kind=str(config.get("kind", "mouse_right")),
            key=str(config.get("key", "space")),
            press_duration_ms=int(config.get("press_duration_ms", 8)),
        )
    raise ValueError(f"Unsupported action mode: {mode}")
