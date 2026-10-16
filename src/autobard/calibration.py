from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import copy

import cv2
import mss
import numpy as np

from .config import save_config
from .models import Rect
from .vision.notes import NoteDetector
from .window import find_window_client_rect, primary_monitor_rect


class CalibrationCancelled(RuntimeError):
    pass


def calibration_instructions(countdown_s: int) -> str:
    delay_text = (
        f"点击“继续”后，AutoBard 会最小化，并等待 {countdown_s} 秒再截图。"
        if countdown_s > 0
        else "点击“继续”后，AutoBard 会最小化并立即准备截图。"
    )
    return (
        "重新校准用于告诉 AutoBard 演奏条和音符区域在画面中的位置。\n\n"
        "第一步：框选完整演奏区域\n"
        "请包含整条横向演奏条、所有音符，以及移动指针。\n\n"
        "第二步：框选音符窄条\n"
        "在第一步的区域内，只紧贴音符所在的横向窄条。\n\n"
        "框选方法：按住鼠标左键拖出矩形；按 Enter 或空格确认本次框选；"
        "按 C 取消校准。\n\n"
        f"{delay_text}\n"
        "请切换到游戏，让演奏条和音符保持清晰可见；F8 可立即截图，Esc 可取消。\n"
        "程序会自动截图，无需微信截图或看图软件。最后确认预览后才保存。"
    )


def _grab(rect: Rect) -> np.ndarray:
    with mss.mss() as sct:
        return np.asarray(sct.grab(rect.as_mss()), dtype=np.uint8)[:, :, :3].copy()


@dataclass(slots=True)
class CalibrationCandidate:
    config: dict
    preview: np.ndarray
    note_count: int


def prepare_calibration(config: dict, parent: Rect, screenshot: np.ndarray,
                        capture_local: Rect, note_local: Rect) -> CalibrationCandidate:
    """Prepare and validate a candidate without modifying settings or files."""
    if screenshot.shape[:2] != (parent.height, parent.width):
        raise ValueError("截图尺寸与游戏区域不一致，请重新截图")
    if not (0 <= capture_local.left < capture_local.right <= parent.width and
            0 <= capture_local.top < capture_local.bottom <= parent.height):
        raise ValueError("演奏区域超出截图，请重新框选")
    if not (0 <= note_local.left < note_local.right <= capture_local.width and
            0 <= note_local.top < note_local.bottom <= capture_local.height):
        raise ValueError("音符区域超出演奏区域，请重新框选")
    capture_crop = capture_local.crop(screenshot)
    result = NoteDetector(config["vision"]["notes"]).detect(note_local.crop(capture_crop))
    if not result.notes:
        raise ValueError("选区中没有识别到音符，请重新框选音符窄条或重新截图")
    candidate = copy.deepcopy(config)
    candidate["capture"]["roi_normalized"] = capture_local.to_normalized(
        Rect(0, 0, parent.width, parent.height))
    candidate["vision"]["note_band_normalized"] = note_local.to_normalized(
        Rect(0, 0, capture_local.width, capture_local.height))
    preview = capture_crop.copy()
    cv2.rectangle(preview, (note_local.left, note_local.top),
                  (note_local.right - 1, note_local.bottom - 1), (255, 200, 0), 1)
    for note in result.notes:
        x = round(note.target + note_local.left)
        cv2.line(preview, (x, note_local.top), (x, note_local.bottom - 1), (0, 255, 0), 1)
    return CalibrationCandidate(candidate, preview, len(result.notes))


def save_calibration(candidate: CalibrationCandidate, output_path: str | Path) -> None:
    save_config(candidate.config, output_path)
    cv2.imwrite(str(Path(output_path).with_name("calibration_preview.jpg")), candidate.preview)


def _select(title: str, image: np.ndarray) -> Rect:
    x, y, w, h = cv2.selectROI(title, image, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow(title)
    if w <= 0 or h <= 0:
        raise CalibrationCancelled("校准已取消")
    return Rect(int(x), int(y), int(x + w), int(y + h))


def calibrate(config: dict, output_path: str | Path) -> Path:
    title = str(config["window"]["title_contains"])
    parent = find_window_client_rect(title)
    if parent is None:
        parent = primary_monitor_rect(int(config["capture"].get("monitor_index", 1)))
    screenshot = _grab(parent)

    print("Step 1/2: drag a box around the full performance bar, including the moving pointer.")
    capture_local = _select("AutoBard Calibration 1/2 - Full performance bar", screenshot)
    capture_crop = capture_local.crop(screenshot)
    print("Step 2/2: drag a tight box around the horizontal note strip inside the first box.")
    note_local = _select("AutoBard Calibration 2/2 - Note strip", capture_crop)

    config["capture"]["roi_normalized"] = capture_local.to_normalized(Rect(0, 0, parent.width, parent.height))
    config["vision"]["note_band_normalized"] = note_local.to_normalized(Rect(0, 0, capture_local.width, capture_local.height))
    save_config(config, output_path)

    detector = NoteDetector(config["vision"]["notes"])
    result = detector.detect(note_local.crop(capture_crop))
    preview = capture_crop.copy()
    for note in result.notes:
        x = round(note.target + note_local.left)
        cv2.line(preview, (x, note_local.top), (x, note_local.bottom), (0, 255, 0), 2)
    preview_path = Path(output_path).with_name("calibration_preview.jpg")
    cv2.imwrite(str(preview_path), preview)
    print(f"Saved {output_path}; initial detector found {len(result.notes)} note candidates.")
    print(f"Preview: {preview_path}")
    return Path(output_path)
