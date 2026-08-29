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


def test_hit_window_allows_a_bounded_early_trigger_inside_the_note() -> None:
    note = Note(0, 179, 204, 191, 1.0)
    scheduler = NoteScheduler(
        [note],
        {"input_latency_ms": 45, "hit_window_ratio": 0.008, "miss_margin_ratio": 0.012},
        581,
    )

    # The compensated trigger is x=186.5. The visual margin remains bounded by
    # the note's left edge: x=181 is too early, while x=182 is accepted.
    assert scheduler.update(0.0, 181.0, 100.0).due == []
    assert scheduler.update(0.02, 182.0, 100.0).due == [note]


def test_model_timing_anticipates_the_next_frame_at_high_speed() -> None:
    config = {
        "input_latency_ms": 45,
        "hit_window_ratio": 0.008,
        "model_input_latency_ms": 50,
        "model_hit_window_ratio": 0.004,
        "miss_margin_ratio": 0.012,
    }
    live_note = Note(0, 395, 426, 410, 1.0)
    model_note = Note(0, 395, 426, 410, 1.0)
    live = NoteScheduler([live_note], config, 581)
    model = NoteScheduler([model_note], config, 581)
    live.update(0.0, 380.0, 362.0)
    model.update(0.0, 380.0, 362.0, use_model=True)

    assert live.update(0.02, 392.3, 362.0).due == []
    assert model.update(0.02, 392.3, 362.0, use_model=True).due == [model_note]


def test_model_window_does_not_fire_a_slow_note_too_early() -> None:
    config = {
        "input_latency_ms": 45,
        "hit_window_ratio": 0.008,
        "model_input_latency_ms": 50,
        "model_hit_window_ratio": 0.004,
        "miss_margin_ratio": 0.012,
    }
    live_note = Note(0, 366, 391, 378, 1.0)
    model_note = Note(0, 366, 391, 378, 1.0)
    live = NoteScheduler([live_note], config, 581)
    model = NoteScheduler([model_note], config, 581)
    live.update(0.0, 360.0, 104.0)
    model.update(0.0, 360.0, 104.0, use_model=True)

    assert live.update(0.02, 368.9, 104.0).due == [live_note]
    assert model.update(0.02, 368.9, 104.0, use_model=True).due == []
    assert model.update(0.04, 373.0, 104.0, use_model=True).due == [model_note]


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


def test_next_pending_note_tracks_scheduler_progress() -> None:
    first = Note(0, 95, 105, 100, 1.0)
    second = Note(1, 195, 205, 200, 1.0)
    scheduler = NoteScheduler([first, second], {"input_latency_ms": 0}, 500)

    assert scheduler.next_pending_note is first
    scheduler.update(0.0, 100, None)
    assert scheduler.next_pending_note is second
