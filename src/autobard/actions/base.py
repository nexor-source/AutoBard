from __future__ import annotations

from abc import ABC, abstractmethod

from autobard.models import Note


class ActionSink(ABC):
    @abstractmethod
    def hit_note(self, note: Note, timestamp: float) -> None:
        raise NotImplementedError

    def start_performance(self, timestamp: float) -> None:
        """Send a startup click through the configured right-button backend.

        The caller must check action.kind=mouse_right. Index -1 identifies a
        startup action in logs and is never counted as a detected note hit.
        """
        self.hit_note(Note(-1, 0.0, 0.0, 0.0, 0.0), timestamp)

    def close(self) -> None:
        """Release resources held by an action sink."""
