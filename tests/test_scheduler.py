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


def test_large_pointer_jump_marks_passed_note_missed() -> None:
    note = Note(0, 95, 105, 100, 1.0)
    scheduler = NoteScheduler(
        [note],
        {"input_latency_ms": 20, "hit_window_ratio": 0.005, "miss_margin_ratio": 0.01},
        500,
    )
    scheduler.update(0.0, 80, 200)

    update = scheduler.update(0.1, 150, None)

    assert update.due == []
    assert update.newly_missed == [note]


def test_new_speed_cannot_move_trigger_behind_pointer_without_firing() -> None:
    note = Note(0, 171, 200, 184.4, 1.0)
    scheduler = NoteScheduler(
        [note],
        {"input_latency_ms": 45, "hit_window_ratio": 0.008, "miss_margin_ratio": 0.012},
        581,
    )

    assert scheduler.update(0.0, 179.5, None).due == []
    update = scheduler.update(0.02, 183.0, 191.0)

    assert update.due == [note]
    assert update.newly_missed == []


def test_hit_window_cannot_fire_before_note_left_edge() -> None:
    note = Note(0, 526, 559, 541.3, 1.0)
    scheduler = NoteScheduler(
        [note],
        {"input_latency_ms": 45, "hit_window_ratio": 0.008, "miss_margin_ratio": 0.012},
        581,
    )

    assert scheduler.update(0.0, 524.5, 304.5).due == []
    assert scheduler.update(0.02, 529.0, 304.5).due == [note]


def test_first_note_is_intentionally_skipped_without_a_hit() -> None:
    first = Note(0, 77, 121, 98.2, 1.0)
    second = Note(1, 186, 198, 191.3, 1.0)
    scheduler = NoteScheduler(
        [first, second],
        {
            "input_latency_ms": 45,
            "hit_window_ratio": 0.008,
            "miss_margin_ratio": 0.012,
            "initial_skip_notes": 1,
        },
        581,
    )

    update = scheduler.update(0.0, 123.5, None)

    assert update.due == []
    assert update.newly_missed == [first]
    assert second.status == "pending"


def test_all_notes_behind_initial_pointer_are_skipped() -> None:
    notes = [
        Note(0, 84, 106, 95, 1.0),
        Note(1, 112, 121, 116, 1.0),
        Note(2, 186, 198, 191, 1.0),
    ]
    scheduler = NoteScheduler(
        notes,
        {"input_latency_ms": 45, "initial_skip_notes": 1},
        581,
    )

    update = scheduler.update(0.0, 128.0, None)

    assert update.due == []
    assert update.newly_missed == notes[:2]
    assert notes[2].status == "pending"
