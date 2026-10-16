"""Read-only replay of recorded pointer observations, not game-grade simulation.

Uses fake capture, vision and actions. Unknown background is not reconstructed;
the changing marker isolates timing gates from the separate stale-image tests.
"""

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import autobard.runtime as runtime
from autobard.models import CaptureFrame, Note, PointerMeasurement, Rect

ROOT = Path(__file__).resolve().parents[2]


def replay(folder):
    meta = json.loads((folder / "session_meta.json").read_text(encoding="utf-8"))
    cfg = meta["config"]
    cfg["debug"]["enabled"] = False
    cfg["session"].update(initial_note_frames=1, initial_frame_spacing_ms=0,
                          post_complete_observe_ms=0)
    cfg["scheduler"].update(initial_skip_notes=0, require_gold_window=True)
    band = Rect(0, 0, 574, 124).subrect_from_normalized(cfg["vision"]["note_band_normalized"])
    with (folder / "tracking.csv").open() as handle:
        rows = list(csv.DictReader(handle))

    class Source:
        index = -1
        timestamp = float(rows[0]["timestamp"]) - 0.02
        x = 6.0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            if 0 <= self.index < len(rows):
                row = rows[self.index]
                self.timestamp = float(row["timestamp"])
                self.x = float(row["candidate_x"]) if row["candidate_x"] else None
            elif self.index >= len(rows):
                self.timestamp += 0.01
                self.x = None
            self.index += 1
            image = np.full((124, 574, 3), 80, np.uint8)
            image[0, 0] = self.index % 255
            if self.x is not None:
                image[:, min(573, max(0, int(round(self.x))))] = (40, 215, 250)
            return CaptureFrame(image, self.timestamp)

    source = Source()

    class Notes:
        def __init__(self, *_args):
            pass

        def detect(self, *_args):
            # Runtime adds band.left, so vision must return crop-local positions.
            return SimpleNamespace(notes=[
                Note(n["index"], n["left"] - band.left, n["right"] - band.left,
                     n["target"] - band.left, 1)
                for n in meta["notes"]
            ], mask=np.zeros((17, 574), np.uint8))

    class Pointer:
        def __init__(self, *_args):
            pass

        def detect(self, *_args, **_kwargs):
            return PointerMeasurement(source.x, 1, 4) if source.x is not None else None

    class Action:
        def __init__(self):
            self.clicks = []

        def hit_note(self, note, timestamp):
            self.clicks.append(dict(note=note.index, time=timestamp,
                                    observed_x=source.x, target=note.target))

    action = Action()
    with patch.object(runtime, "create_capture", lambda *_: source), \
         patch.object(runtime, "NoteDetector", Notes), \
         patch.object(runtime, "PointerDetector", Pointer), \
         patch.object(runtime.time, "perf_counter", lambda: source.timestamp):
        result = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), action).run()
    old_hits = [row for row in rows if row["events"].startswith("H")]
    return dict(session=folder.name, old_click_count=len(old_hits),
                new_policy_click_count=result.hit_count, missed=result.missed_count,
                new_clicks=action.clicks, old_first_two=[
                    {k: row[k] for k in ("timestamp", "events", "pointer_x", "measured_x", "speed")}
                    for row in old_hits[:2]
                ])


if __name__ == "__main__":
    reports = []
    for folder in sorted((ROOT / "debug_output").glob("20261016_*")):
        if not "20261016_145600" <= folder.name < "20261016_150111":
            continue
        if not (folder / "session_meta.json").exists():
            continue
        report = replay(folder)
        reports.append(report)
        print(folder.name, report["old_click_count"], "->", report["new_policy_click_count"])
    Path(__file__).with_name("1500_shadow_timing.json").write_text(
        json.dumps(reports, indent=2) + "\n", encoding="utf-8",
    )
