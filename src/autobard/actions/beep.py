from __future__ import annotations

import logging
import os

from autobard.models import Note

from .base import ActionSink

LOGGER = logging.getLogger("autobard.action")


class BeepAction(ActionSink):
    def hit_note(self, note: Note, timestamp: float) -> None:
        if os.name == "nt":
            import winsound
            winsound.Beep(1100, 18)
        else:
            print("\a", end="", flush=True)
        LOGGER.info("BEEP hit note=%d", note.index)
