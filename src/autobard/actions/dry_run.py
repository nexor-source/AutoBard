from __future__ import annotations

import logging

from autobard.models import Note

from .base import ActionSink

LOGGER = logging.getLogger("autobard.action")


class DryRunAction(ActionSink):
    def hit_note(self, note: Note, timestamp: float) -> None:
        LOGGER.info("DRY-RUN hit note=%d target=%.1f t=%.6f", note.index, note.target, timestamp)
