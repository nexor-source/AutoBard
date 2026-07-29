from autobard.models import Note
from autobard.timing.scheduler import NoteScheduler


def test_scheduler_triggers_each_note_once() -> None:
    notes = [Note(0, 95, 105, 100, 1.0), Note(1, 195, 205, 200, 1.0)]
    scheduler = NoteScheduler(notes, {"input_latency_ms": 0, "hit_window_ratio": 0.005, "miss_margin_ratio": 0.01}, 500)
    assert scheduler.update(0.0, 80, 100).due == []
    first = scheduler.update(0.1, 110, 100).due
    assert [note.index for note in first] == [0]
    assert scheduler.update(0.2, 130, 100).due == []
    second = scheduler.update(0.3, 210, 100).due
    assert [note.index for note in second] == [1]
    assert scheduler.complete
