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
        self.initial_skip_notes = max(0, int(config.get("initial_skip_notes", 0)))
        self._has_initial_pointer = False
        self.previous_x: float | None = None

    def update(self, timestamp: float, pointer_x: float, speed: float | None) -> SchedulerUpdate:
        due: list[Note] = []
        missed: list[Note] = []
        latency_lead = max(0.0, speed or 0.0) * self.latency_s

        if not self._has_initial_pointer:
            # Starting the detector requires a second right-click after the
            # performance has begun. The first note is intentionally sacrificed,
            # and any other note already behind the first observed pointer must
            # never produce a delayed click or a false post-hit reanchor.
            for index, note in enumerate(self.notes):
                if note.status == "pending" and (
                    index < self.initial_skip_notes or note.target <= pointer_x
                ):
                    note.status = "missed"
                    missed.append(note)
            self._has_initial_pointer = True

        for note in self.notes:
            if note.status != "pending":
                continue
            trigger_x = note.target - latency_lead
            crossed = self.previous_x is not None and self.previous_x < trigger_x <= pointer_x
            reached = pointer_x >= trigger_x
            # A very large detector jump must not turn already-passed notes into
            # delayed clicks. Normal frame-to-frame crossings remain inside the
            # note bounds plus the configured miss margin.
            if pointer_x > note.right + self.miss_margin:
                note.status = "missed"
                missed.append(note)
            elif crossed or reached:
                note.status = "hit"
                note.triggered_at = timestamp
                due.append(note)

        self.previous_x = pointer_x
        return SchedulerUpdate(due, missed)

    @property
    def pending_count(self) -> int:
        return sum(note.status == "pending" for note in self.notes)

    @property
    def next_pending_note(self) -> Note | None:
        return next((note for note in self.notes if note.status == "pending"), None)

    @property
    def complete(self) -> bool:
        return all(note.status != "pending" for note in self.notes)
