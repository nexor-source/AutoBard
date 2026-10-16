# Issue #2 诊断（2026-10-14）

问题：https://github.com/nexor-source/AutoBard/issues/2

## 已知事实与限制

- 标题为 `fails to detect`，正文仅描述满足条件后没有动作。
- 创建时间为 2026-04-20 20:21:39 UTC（北京时间 4 月 21 日），无评论、截图、版本或日志。
- 当时仓库最新提交为 `f06d9e8`，尚未进行 2.x 重构；不能把它视为 v2.1.1 的反馈。
- 可以确认旧代码存在问题，但缺少报告者的环境，不能确认他的故障就是下面的溢出。

## 可复现的旧脚本缺陷

`legacy/true.py`、`legacy/true2.py`、`legacy/hotfix81.py` 直接对 NumPy `uint8` 标量加减颜色容差。在当前 NumPy 2.5.1 环境中，算术会先溢出，之后 `np.clip` 无法恢复原值。

- 音符红色通道：232 + 44 原本应限制到 255，实际回绕到 20。
- 指针红色通道：243 + 50 原本应限制到 255，实际回绕到 37。
- 因而颜色上限小于下限，连精确目标颜色也被 `cv2.inRange` 排除。
- hotfix81 的音符蓝色通道还存在减容差后下溢的问题。

修复：用有符号 `int32` 计算上下界，限制到 0–255 后再转换为 `uint8`。无需通过扩大容差或调整截图位置来修复这处算术错误。

## 验证

`tests/test_legacy_detection.py` 提取并执行三个脚本的实际识别函数，用合成音符块和指针线作为截图输入，不启动旧脚本的鼠标钩子或演奏循环。

- 修复前：6 项回归测试均因溢出失败。
- 修复后：6 项均识别到正确位置的目标轮廓。
- 完整测试：94 passed。
- 未验证报告者的游戏环境；合成图测试不能替代他的实际复测。

修复目前仅在本地，未发布或回复 issue。v2.1.1 使用新的识别方法，不执行以上旧脚本的颜色计算。

## 建议处理顺序

1. 请报告者使用已发布的 v2.1.1，重新校准游戏画面；旧脚本还依赖固定或按分辨率缩放的截图位置，未必适用于新的 HUD。
2. 若仍失败，提供版本、分辨率/HUD 缩放、输出模式、启动到失败期间的日志，以及失败运行的 `debug_output` 文件。
3. 日志没有 `Detected ... notes`：检查截图和音符校准；有音符但没有 `Pointer acquired`：检查指针区域及图像；有 `DRY-RUN hit`：已经识别命中，但当前模式不会发送输入。实际点击需要 GUI 的 `system_input` 模式及其现有风险确认和驱动要求。

## 可用于后续回复的英文草稿（尚未发送）

This report predates the 2.x rewrite. Please try v2.1.1 and recalibrate the capture area using the game screen. We reproduced a NumPy 2 compatibility bug in the legacy scripts: uint8 color-threshold arithmetic can overflow and reject even the target color. The current detector uses a different method.

If the problem persists, please share your version, display resolution/HUD scale, action mode, startup/session logs, and the failed session's debug_output. If the log contains "DRY-RUN hit", detection is working but dry_run does not send clicks. This information will help distinguish capture/detection failures from input-output failures.
