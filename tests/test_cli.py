from autobard.cli import _build_parser


def test_input_command_parses_delay() -> None:
    args = _build_parser().parse_args(
        ["test-input", "--delay-s", "2.5", "--mouse-backend", "send_input", "--duration-ms", "100"]
    )

    assert args.command == "test-input"
    assert args.delay_s == 2.5
    assert args.mouse_backend == "send_input"
    assert args.duration_ms == 100


def test_input_command_accepts_viiper_backend() -> None:
    args = _build_parser().parse_args(["test-input", "--mouse-backend", "viiper"])

    assert args.mouse_backend == "viiper"
