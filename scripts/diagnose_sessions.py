"""Read saved sessions without capture, input devices, or changing source data."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from autobard.tracking import PostActionTrajectoryVerifier
from autobard.tracking.speed import RobustSpeedEstimator


def replay_model(rows: list[dict], meta: dict, history: int) -> dict:
    """Conditional replay: reuse recorded observations and actual click times.

    This evaluates the trajectory only. New clicks would change the game frames,
    so this must never be presented as an end-to-end success-rate simulation.
    """
    estimator = RobustSpeedEstimator(history, 4)
    speed = None
    anchor_t = anchor_x = None
    verifier = None
    errors = []
    click_errors = []
    for row in rows:
        t = float(row["timestamp"])
        x = float(row["measured_x"]) if row["measured_x"] else None
        if speed is None and x is not None:
            estimator.add(t, x, float(row["confidence"]))
        if speed is not None and x is not None:
            if verifier is not None:
                result = verifier.observe(t, x)
                if result is not None:
                    anchor_t, anchor_x = result.timestamp, result.x
                    verifier = None
            prediction = anchor_x + speed * (t - anchor_t)
            errors.append(abs(prediction - x))
        if "H" in row["events"]:
            index = int(row["events"].split("H")[-1])
            if speed is None:
                speed = estimator.fit().speed
                anchor_t, anchor_x = t, x
            else:
                click_errors.append(abs(anchor_x + speed * (t - anchor_t) - x) if x is not None else None)
            action_t = t + float(row["action_submit_delay_ms"]) / 1000
            predicted = anchor_x + speed * (action_t - anchor_t)
            verifier = PostActionTrajectoryVerifier(
                action_timestamp=action_t, expected_x=predicted,
                note_target=meta["notes"][index]["target"], speed=speed,
                input_latency_s=0.045 if row["schedule_mode"] == "live" else 0.05,
                required_samples=3,
            )
    return {"history": history, "locked_speed": round(speed, 3),
            "median_error_px": round(float(np.median(errors)), 3),
            "p90_error_px": round(float(np.percentile(errors, 90)), 3),
            "click_errors_px": [round(e, 3) if e is not None else None for e in click_errors]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    results = []
    for folder in sorted(Path("debug_output").glob(args.date + "_*")):
        meta = json.loads((folder / "session_meta.json").read_text(encoding="utf-8"))
        with (folder / "tracking.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        start = float(rows[0]["timestamp"])
        hits = [i for i, row in enumerate(rows) if "H" in row["events"]]
        segments = []
        for a, b in zip([0] + hits, hits + [len(rows) - 1]):
            # Exclude the immediate post-click animation and note overlap.
            samples = [r for r in rows[a:b] if r["measured_x"] and
                       float(r["timestamp"]) - float(rows[a]["timestamp"]) > 0.2]
            if len(samples) < 8:
                continue
            ts = np.array([float(r["timestamp"]) for r in samples])
            xs = np.array([float(r["measured_x"]) for r in samples])
            # Median slopes across sample pairs separated by at least 200 ms.
            dt = ts[None, :] - ts[:, None]
            dx = xs[None, :] - xs[:, None]
            valid = dt > 0.2
            if not valid.any():
                continue
            slope = float(np.median(dx[valid] / dt[valid]))
            segments.append({"first_frame": samples[0]["frame"],
                             "last_frame": samples[-1]["frame"],
                             "observed_speed": round(slope, 3),
                             "locked_speed": samples[-1]["speed"]})
        events = []
        for i in hits:
            r = rows[i]
            index = int(r["events"].split("H")[-1])
            note = meta["notes"][index]
            observed = float(r["measured_x"]) if r["measured_x"] else None
            events.append({"event": r["events"], "frame": r["frame"],
                           "time_s": round(float(r["timestamp"]) - start, 3),
                           "target": note["target"], "scheduled_x": float(r["pointer_x"]),
                           "measured_x": observed,
                           "model_error_px": round(float(r["pointer_x"]) - observed, 3) if observed is not None else None})
        image_positions = []
        for path in sorted(folder.glob("event_*.jpg")):
            im = cv2.imread(str(path))
            h, w = im.shape[:2]
            hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
            # Outside the staff and its overlay markers: the physical gold cursor
            # spans these rows; the magenta debug line does not satisfy this mask.
            mask = ((hsv[:, :, 0] >= 12) & (hsv[:, :, 0] <= 38) &
                    (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 150))
            bands = np.r_[np.arange(39, 47), np.arange(80, min(h, 95))]
            scores = mask[bands].sum(axis=0)
            peak = int(np.argmax(scores))
            near = np.arange(max(0, peak - 3), min(w, peak + 4))
            weights = scores[near]
            x = float(np.average(near, weights=weights)) if weights.sum() else None
            image_positions.append({"file": path.name, "physical_cursor_x": round(x, 2) if x is not None else None,
                                    "gold_row_support": int(scores[peak]), "rows": len(bands)})
        results.append({"session": folder.name, "seconds": round(float(rows[-1]["timestamp"]) - start, 4),
                        "pending": int(rows[-1]["pending"]), "events": events,
                        "segments": segments, "image_positions": image_positions,
                        "model_replay": [replay_model(rows, meta, n) for n in [18, 36, 60, 90]]})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in results:
        print(r["session"], "duration", r["seconds"], "pending", r["pending"])
        print("segment speeds:", [(s["observed_speed"], s["locked_speed"]) for s in r["segments"]])
        print("click errors:", [e["model_error_px"] for e in r["events"]])
        print("conditional replay:", r["model_replay"])
        print("physical cursors:", [(p["file"], p["physical_cursor_x"], p["gold_row_support"]) for p in r["image_positions"] if "p00" in p["file"]])


if __name__ == "__main__":
    main()
