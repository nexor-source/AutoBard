from __future__ import annotations

import argparse
import logging
import sys
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
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger(__name__).exception("Command failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
