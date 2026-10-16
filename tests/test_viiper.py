import struct

from autobard.actions.viiper import MOUSE_BUTTON_RIGHT, ViiperAction
from autobard.models import Note


class FakeStream:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def settimeout(self, _timeout) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_viiper_right_click_uses_mouse_hid_reports(monkeypatch) -> None:
    stream = FakeStream()
    requests: list[str] = []

    monkeypatch.setattr(ViiperAction, "_ensure_server", lambda self: None)

    def request(_self, command: str) -> dict:
        requests.append(command)
        if command == "bus/create":
            return {"busId": 4}
        if command.startswith("bus/4/add"):
            return {"devId": "2"}
        return {}

    monkeypatch.setattr(ViiperAction, "_request", request)
    monkeypatch.setattr("autobard.actions.viiper.socket.create_connection", lambda *_args, **_kwargs: stream)
    monkeypatch.setattr("autobard.actions.viiper.time.sleep", lambda _duration: None)

    action = ViiperAction("mouse_right", 10)
    action.hit_note(Note(0, 10, 20, 15, 1.0), 1.25)
    action.close()

    neutral = struct.pack("<Bhhhh", 0, 0, 0, 0, 0)
    pressed = struct.pack("<Bhhhh", MOUSE_BUTTON_RIGHT, 0, 0, 0, 0)
    assert stream.sent == [b"bus/4/2\0", pressed, neutral, neutral]
    assert stream.closed
    assert requests == [
        "bus/create",
        'bus/4/add {"type":"mouse"}',
        "bus/4/remove 2",
        "bus/remove 4",
    ]


def test_startup_uses_the_same_right_button_output_as_note_hits(monkeypatch):
    # Exercise the inherited startup operation through the real VIIPER hit path.
    import threading

    stream = FakeStream()
    action = object.__new__(ViiperAction)
    action._lock = threading.Lock()
    action._closed = False
    action._stream = stream
    action.duration = 0
    action.start_performance(1.0)
    assert stream.sent == [
        struct.pack("<Bhhhh", MOUSE_BUTTON_RIGHT, 0, 0, 0, 0),
        struct.pack("<Bhhhh", 0, 0, 0, 0, 0),
    ]
