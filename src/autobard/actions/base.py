from __future__ import annotations

from abc import ABC, abstractmethod

from autobard.models import Note


class ActionSink(ABC):
    @abstractmethod
    def hit_note(self, note: Note, timestamp: float) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Release resources held by an action sink."""
