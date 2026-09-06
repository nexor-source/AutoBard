from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG_PATH = Path("config/settings.json")


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _package_defaults() -> dict[str, Any]:
    # A compact fallback allows the package to run even if the external file was moved.
    return {
        "window": {"title_contains": "Dark and Darker", "fallback_to_primary_monitor": True},
        "calibration": {"countdown_s": 5},
        "capture": {"backend": "mss", "target_fps": 120, "monitor_index": 1,
                    "roi_normalized": [0.3984375, 0.7597222, 0.6015625, 0.8472222]},
        "vision": {
            "note_band_normalized": [0.0, 0.4047619, 1.0, 0.6507937],
            "notes": {"pixel_quantile": 0.76, "column_coverage": 0.20,
                      "min_width_ratio": 0.009, "max_width_ratio": 0.20,
                      "merge_gap_ratio": 0.006, "min_confidence": 0.20,
                      "min_brightness_p90": 60, "min_vertical_coverage": 0.68,
                      "edge_vertical_coverage": 0.35,
                      "shoulder_merge_gap_ratio": 0.012,
                      "shoulder_max_extension_ratio": 0.025},
            "pointer": {"analysis_y": [0.36, 0.72], "excluded_y": [[0.47, 0.59]],
                        "motion_weight": 0.48, "edge_weight": 0.30, "color_weight": 0.22,
                        "prediction_weight": 0.70, "prediction_sigma_ratio": 0.035,
                        "prediction_search_ratio": 0.06,
                        "bootstrap_border_ratio": 0.03,
                        "bootstrap_search_ratio": 0.10,
                        "min_confidence": 0.20, "max_width_ratio": 0.04},
        },
        "tracking": {"history_size": 18, "min_fit_samples": 4, "min_speed_px_s": 20.0,
                     "max_speed_px_s": 3000.0, "backward_tolerance_ratio": 0.025,
                     "max_prediction_error_ratio": 0.05, "prediction_hold_ms": 90,
                     "speed_hold_ms": 1200, "bootstrap_confirm_frames": 4,
                     "bootstrap_min_displacement_ratio": 0.003,
                     "bootstrap_backward_tolerance_ratio": 0.004,
                     "bootstrap_max_gap_ms": 80, "bootstrap_expand_ms": 150,
                     "bootstrap_min_r_squared": 0.72,
                     "post_action_reanchor_samples": 3},
        "scheduler": {"input_latency_ms": 22, "hit_window_ratio": 0.008,
                      "model_input_latency_ms": 27, "model_hit_window_ratio": 0.004,
                      "early_trigger_tolerance_ratio": 0.001,
                      "miss_margin_ratio": 0.012, "initial_skip_notes": 1,
                      "model_schedule_max_note_width_ratio": 0.05},
        "session": {"initial_note_frames": 5, "initial_frame_spacing_ms": 8,
                    "pointer_start_delay_ms": 0,
                    "max_duration_s": 8.0, "pointer_lost_timeout_ms": 320,
                    "minimum_runtime_ms": 250, "post_complete_observe_ms": 150},
        "action": {
            "mode": "dry_run",
            "kind": "mouse_right",
            "key": "space",
            "mouse_backend": "viiper",
            "press_duration_ms": 20,
            "acknowledge_online_risk": False,
            "viiper": {
                "executable": "runtime/viiper.exe",
                "host": "127.0.0.1",
                "api_port": 3242,
                "usb_port": 3241,
                "startup_timeout_s": 10.0,
            },
        },
        "hotkeys": {"double_right_click_interval_ms": 350,
                    "abort": "<f9>", "quit": "<f10>"},
        "debug": {"enabled": True, "output_dir": "debug_output",
                  "save_every_n_frames": 0, "record_video": False,
                  "event_follow_frames": 6},
        "updates": {"enabled": True, "check_on_start": True,
                    "github_repo": "nexor-source/AutoBard",
                    "asset_name": "AutoBard-win64.zip", "timeout_s": 15.0},
    }


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = _package_defaults()
    selected = Path(path) if path else DEFAULT_CONFIG_PATH
    if selected.exists():
        with selected.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("Configuration root must be a JSON object")
        _deep_merge(config, loaded)
    validate_config(config)
    return config


def save_config(config: Mapping[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_config(config: Mapping[str, Any]) -> None:
    roi = config["capture"]["roi_normalized"]
    note_roi = config["vision"]["note_band_normalized"]
    for name, values in (("capture.roi_normalized", roi), ("vision.note_band_normalized", note_roi)):
        if len(values) != 4 or not all(0 <= float(v) <= 1 for v in values):
            raise ValueError(f"{name} must contain four values in [0, 1]")
        if values[2] <= values[0] or values[3] <= values[1]:
            raise ValueError(f"{name} has invalid bounds")
    if int(config["capture"]["target_fps"]) <= 0:
        raise ValueError("capture.target_fps must be positive")
    countdown_s = int(config.get("calibration", {}).get("countdown_s", 5))
    if not 0 <= countdown_s <= 60:
        raise ValueError("calibration.countdown_s must be between 0 and 60")
    pointer_delay_ms = int(config.get("session", {}).get("pointer_start_delay_ms", 0))
    if not 0 <= pointer_delay_ms <= 2000:
        raise ValueError("session.pointer_start_delay_ms must be between 0 and 2000")
