import threading

from autobard.feedback import SessionSounds


def test_disabled_sound_does_not_play_or_create_a_worker(monkeypatch):
    monkeypatch.setattr(SessionSounds, "_play", lambda _: (_ for _ in ()).throw(AssertionError()))
    sounds = SessionSounds(False)
    sounds.play("takeover")
    sounds.play("end")
    sounds.close()
    assert sounds._thread is None


def test_sounds_are_ordered_and_do_not_block_caller(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    ended = threading.Event()
    cues = []

    def play(cue):
        cues.append(cue)
        if cue == "takeover":
            entered.set()
            release.wait(1)
        else:
            ended.set()

    monkeypatch.setattr(SessionSounds, "_play", staticmethod(play))
    sounds = SessionSounds(True)
    try:
        sounds.play("takeover")
        assert entered.wait(1)
        sounds.play("end")
        assert not ended.is_set()  # The caller returned while audio is still busy.
        release.set()
        assert ended.wait(1)
    finally:
        release.set()
        sounds.close()
    assert cues == ["takeover", "end"]
    assert not sounds._thread.is_alive()
