from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import __version__
from .calibration import calibrate
from .config import load_config
from .inspection import inspect_image
from .runtime import AutoBardSession
from .window import resolve_capture_rect


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autobard", description="AutoBard refactored visual detector")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", default="config/settings.json", help="Path to JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the global-hotkey service")
    run.add_argument("--once", action="store_true", help="Run one session immediately")

    calibration = sub.add_parser("calibrate", help="Interactively select capture and note ROIs")
    calibration.add_argument("--output", default="config/settings.json")

    inspect = sub.add_parser("inspect-image", help="Run note detection on a screenshot")
    inspect.add_argument("image")
    inspect.add_argument("--output", default="debug_output/inspect.jpg")
    inspect.add_argument("--auto-locate", action="store_true")

    video = sub.add_parser("analyze-video", help="Analyze a recorded performance without sending input")
    video.add_argument("video")
    video.add_argument("--output-dir", default="debug_output/offline")
    video.add_argument("--start-s", type=float, default=0.0)
    video.add_argument("--roi-is-frame", action="store_true", help="The video already contains only the calibrated ROI")

    test_input = sub.add_parser("test-input", help="Send one configured input after a countdown")
    test_input.add_argument("--delay-s", type=float, default=5.0, help="Seconds to wait before sending input")
    test_input.add_argument(
        "--mouse-backend",
        choices=["viiper", "mouse_event", "send_input"],
        help="Temporarily override action.mouse_backend",
    )
    test_input.add_argument("--duration-ms", type=int, help="Temporarily override the press duration")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
        if args.command == "run":
            if args.once:
                _, capture_rect = resolve_capture_rect(config)
                result = AutoBardSession(config, capture_rect).run()
                print(result)
            else:
                from .service import HotkeyService

                HotkeyService(config).run()
        elif args.command == "calibrate":
            calibrate(config, args.output)
        elif args.command == "inspect-image":
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            inspect_image(args.image, config, output, args.auto_locate)
        elif args.command == "analyze-video":
            from .offline import analyze_video

            result = analyze_video(args.video, config, args.output_dir, args.start_s, args.roi_is_frame)
            print(result)
        elif args.command == "test-input":
            from .actions import create_action_sink
            from .models import Note
            from pynput import mouse

            action_config = dict(config["action"])
            if args.mouse_backend is not None:
                action_config["mouse_backend"] = args.mouse_backend
            if args.duration_ms is not None:
                action_config["press_duration_ms"] = max(0, int(args.duration_ms))
            action = create_action_sink(action_config)
            try:
                delay_s = max(0.0, float(args.delay_s))
                print(
                    f"Sending one configured input in {delay_s:g}s; focus the test target now.",
                    flush=True,
                )
                time.sleep(delay_s)

                observed: list[tuple[str, bool]] = []

                def observe_click(_x: int, _y: int, button: mouse.Button, pressed: bool) -> None:
                    if button == mouse.Button.right:
                        observed.append(("right", pressed))

                listener = mouse.Listener(on_click=observe_click)
                listener.start()
                listener.wait()
                try:
                    timestamp = time.perf_counter()
                    action.hit_note(Note(0, 0, 1, 0.5, 1.0), timestamp)
                    time.sleep(0.25)
                finally:
                    listener.stop()
                    listener.join(timeout=1.0)
                print(f"Windows hook observed: {observed or 'no right-button events'}", flush=True)
                print("Input call completed.", flush=True)
            finally:
                action.close()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger(__name__).exception("Command failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
