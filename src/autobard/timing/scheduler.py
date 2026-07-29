from __future__ import annotations

from dataclasses import dataclass

from autobard.models import Note


@dataclass(slots=True)
class SchedulerUpdate:
    due: list[Note]
    newly_missed: list[Note]


class NoteScheduler:
    def __init__(self, notes: list[Note], config: dict, frame_width: int) -> None:
        self.notes = sorted(notes, key=lambda note: note.target)
        self.frame_width = frame_width
        self.latency_s = float(config.get("input_latency_ms", 22)) / 1000.0
        self.hit_window = max(1.0, frame_width * float(config.get("hit_window_ratio", 0.008)))
        self.miss_margin = max(1.0, frame_width * float(config.get("miss_margin_ratio", 0.012)))
        self.previous_x: float | None = None

    def update(self, timestamp: float, pointer_x: float, speed: float | None) -> SchedulerUpdate:
        due: list[Note] = []
        missed: list[Note] = []
        latency_lead = max(0.0, speed or 0.0) * self.latency_s

        for note in self.notes:
            if note.status != "pending":
                continue
            trigger_x = note.target - latency_lead
            crossed = self.previous_x is not None and self.previous_x < trigger_x <= pointer_x
            inside = abs(pointer_x - trigger_x) <= self.hit_window
            if crossed or inside:
                note.status = "hit"
                note.triggered_at = timestamp
                due.append(note)
            elif pointer_x > note.right + self.miss_margin:
                note.status = "missed"
                missed.append(note)

        self.previous_x = pointer_x
        return SchedulerUpdate(due, missed)

    @property
    def pending_count(self) -> int:
        return sum(note.status == "pending" for note in self.notes)

    @property
    def complete(self) -> bool:
        return all(note.status != "pending" for note in self.notes)
