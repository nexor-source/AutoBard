from __future__ import annotations

import argparse
import statistics
import time

from autobard.capture import create_capture
from autobard.config import load_config
from autobard.window import resolve_capture_rect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/settings.json")
    parser.add_argument("--backend", choices=["auto", "dxcam", "mss"], default=None)
    parser.add_argument("--frames", type=int, default=500)
    args = parser.parse_args()
    config = load_config(args.config)
    _, rect = resolve_capture_rect(config)
    backend = args.backend or config["capture"]["backend"]
    source = create_capture(backend, rect, int(config["capture"]["target_fps"]))
    times = []
    with source:
        source.read()
        for _ in range(args.frames):
            start = time.perf_counter()
            source.read()
            times.append(time.perf_counter() - start)
    total = sum(times)
    print(f"backend={backend} region={rect.width}x{rect.height} frames={len(times)}")
    print(f"effective_fps={len(times)/total:.1f} mean_ms={statistics.mean(times)*1000:.3f} p95_ms={statistics.quantiles(times, n=20)[18]*1000:.3f}")


if __name__ == "__main__":
    main()
