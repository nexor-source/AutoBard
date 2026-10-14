"""Synthetic cursor stress test on saved, unannotated game backgrounds.

This is NOT replay of the game's actual pointer, feedback, or input handling.
It checks known-location detection in the presence of the captured note artwork.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import types
from pathlib import Path

import cv2
import numpy as np

from autobard.vision.pointer import PointerDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline-ref", default="HEAD")
    args = parser.parse_args()
    source = subprocess.check_output([
        "git", "show", args.baseline_ref + ":src/autobard/vision/pointer.py",
    ], text=True)
    baseline = types.ModuleType("autobard.vision.pointer_baseline")
    baseline.__package__ = "autobard.vision"
    exec(compile(source, "pointer_baseline.py", "exec"), baseline.__dict__)
    original = json.loads((Path("diagnostics") / args.date / "settings_before.json").read_text(encoding="utf-8"))
    current = json.loads(Path("config/settings.json").read_text(encoding="utf-8"))
    result = {"kind": "synthetic known cursor on real backgrounds, not live replay",
              "speed_px_s": 60, "fps": 70, "baseline_ref": subprocess.check_output(
                  ["git", "rev-parse", args.baseline_ref], text=True).strip(),
              "cases": []}
    for folder in sorted(Path("debug_output").glob(args.date + "_*")):
        background = cv2.imread(str(folder / "initial_capture.png"))
        # Remove the original left-edge pointer in this controlled test only.
        # The file on disk remains untouched.
        background[:, :40] = background[:, 40:41]
        for drift in [0, 12]:
            for label in ["before", "after"]:
                detector = (baseline.PointerDetector(original["vision"]["pointer"])
                            if label == "before" else PointerDetector(
                                current["vision"]["pointer"],
                                (current["vision"]["note_band_normalized"][1],
                                 current["vision"]["note_band_normalized"][3])))
                errors = []
                missing = 0
                for index in range(560):
                    x = round(80 + index * 60 / 70)
                    frame = background.copy()
                    cv2.line(frame, (x, 4), (x, 119), (40, 190, 245), 2)
                    measurement = detector.detect(frame, predicted_x=x + drift)
                    if measurement is None:
                        missing += 1
                    else:
                        errors.append(abs(measurement.x - x))
                case = {"session": folder.name, "variant": label,
                        "prediction_drift_px": drift, "frames": 560,
                        "missing": missing, "median_error_px": round(float(np.median(errors)), 3),
                        "p90_error_px": round(float(np.percentile(errors, 90)), 3),
                        "max_error_px": max(errors),
                        "within_4px_count": int(sum(e <= 4 for e in errors))}
                result["cases"].append(case)
                print(case, flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
