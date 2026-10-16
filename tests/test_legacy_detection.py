"""Exercise archived detectors without importing their mouse hooks or main loops."""

import ast
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest


LEGACY = Path(__file__).resolve().parents[1] / "legacy"


def detector(script, function_name, image, monkeypatch):
    tree = ast.parse((LEGACY / script).read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert len(functions) == 1

    class Capture:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def grab(self, _monitor):
            return cv2.cvtColor(image.copy(), cv2.COLOR_BGR2BGRA)

    monkeypatch.setattr(cv2, "imwrite", lambda *_args: True)
    namespace = {
        "np": np,
        "cv2": cv2,
        "mss": SimpleNamespace(mss=Capture),
        "pyautogui": SimpleNamespace(
            screenshot=lambda **_kwargs: cv2.cvtColor(image.copy(), cv2.COLOR_BGR2RGB)
        ),
        "scale": lambda value, _axis: value,
        "scale_x": 1,
        "scale_y": 1,
        "debug_mode": False,
        "note_bgr": [14, 150, 232],
        "pointer_bgr": [61, 211, 243],
        "note_tolerance": 50,
        "pointer_tolerance": 50,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(LEGACY / script), "exec"), namespace)
    return namespace[function_name]()


@pytest.mark.parametrize("script", ["true.py", "true2.py", "hotfix81.py"])
@pytest.mark.parametrize("kind", ["note", "pointer"])
def test_legacy_detects_target_colors_at_uint8_boundaries(script, kind, monkeypatch):
    # Hotfix colors also underflow in the blue channel when tolerance is subtracted.
    colors = (
        {"note": (14, 150, 232), "pointer": (61, 211, 243)}
        if script == "hotfix81.py"
        else {"note": (54, 178, 232), "pointer": (118, 196, 243)}
    )
    image = np.zeros((31 if kind == "note" else 126, 520, 3), dtype=np.uint8)
    if kind == "note":
        image[5:25, 200:220] = colors[kind]
    else:
        image[10:115, 200:203] = colors[kind]
    with np.errstate(over="raise"):
        contours = detector(script, f"get_{kind}_area", image, monkeypatch)
    assert len(contours) == 1
    x, _y, width, _height = cv2.boundingRect(contours[0])
    assert x <= 201 <= x + width
