from __future__ import annotations

import numpy as np
import pytest

from autobard.calibration import (
    CalibrationCancelled,
    _select,
    calibration_instructions,
)
from autobard.config import load_config, validate_config


def test_calibration_instructions_explain_both_steps_and_controls() -> None:
    text = calibration_instructions(7)

    assert "第一步" in text
    assert "完整演奏区域" in text
    assert "第二步" in text
    assert "音符窄条" in text
    assert "Enter" in text
    assert "空格" in text
    assert "按 C 取消" in text
    assert "等待 7 秒" in text
    assert "切换到游戏" in text


def test_select_raises_specific_cancel_exception(monkeypatch) -> None:
    monkeypatch.setattr("autobard.calibration.cv2.selectROI", lambda *_args, **_kwargs: (0, 0, 0, 0))
    monkeypatch.setattr("autobard.calibration.cv2.destroyWindow", lambda _title: None)

    with pytest.raises(CalibrationCancelled, match="校准已取消"):
        _select("test", np.zeros((10, 10, 3), dtype=np.uint8))


def test_calibration_countdown_default_and_validation(tmp_path) -> None:
    config = load_config(tmp_path / "missing.json")

    assert config["calibration"]["countdown_s"] == 5
    assert config["session"]["pointer_start_delay_ms"] == 0
    config["calibration"]["countdown_s"] = 60
    validate_config(config)
    config["calibration"]["countdown_s"] = 61
    with pytest.raises(ValueError, match="calibration.countdown_s"):
        validate_config(config)


def test_pointer_start_delay_validation(tmp_path) -> None:
    config = load_config(tmp_path / "missing.json")
    config["session"]["pointer_start_delay_ms"] = 2000
    validate_config(config)
    config["session"]["pointer_start_delay_ms"] = 2001
    with pytest.raises(ValueError, match="session.pointer_start_delay_ms"):
        validate_config(config)
