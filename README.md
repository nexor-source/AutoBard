# AutoBard 2.0（重构版）

这是对旧版单文件脚本的完整重构。旧实现保存在 `legacy/`，新实现默认只做视觉检测和日志输出，不会主动发送键鼠信号。

> 在线游戏可能禁止自动化操作并导致账号处罚。项目不包含反作弊绕过、隐藏进程或驱动级输入。开发和调参请优先使用 `dry_run`、录像或截图。

## 本次重构解决了什么

- **截图对象全程复用**：Windows 优先使用 DXcam，失败时自动回退 MSS。
- **只截取小 ROI**：坐标相对于游戏窗口客户区保存，不再按整块显示器分辨率硬缩放。
- **颜色不再写死**：音符使用 Lab/HSV 自适应暖色评分、列覆盖率和几何区间检测。
- **指针不再只看固定 RGB**：融合帧间运动、垂直边缘、暖色特征以及上一帧预测位置。
- **利用匀速运动**：鲁棒直线拟合估计 `x(t)=vt+b`，短时间漏检时允许预测补偿。
- **无阻塞命中状态机**：每个音符只触发一次，不再用 `sleep(0.15)` 防重复。
- **可离线调试**：保存初始图、音符遮罩、叠加图、跟踪 CSV，可选录制调试视频。
- **可测试**：包含亮度变化、速度拟合、指针运动和调度器单元测试。

## 目录

```text
src/autobard/
├── capture/        # DXcam / MSS，可替换截图后端
├── vision/         # 演奏条候选、音符检测、指针检测
├── tracking/       # 指针跟踪和鲁棒速度估计
├── timing/         # 一次性音符调度器
├── actions/        # dry-run / beep / SendInput
├── debug/          # 叠加图、CSV、视频记录
├── calibration.py  # 两步框选校准
├── runtime.py      # 单次演奏状态机
└── service.py      # F8/F9/F10 全局热键服务
```

## 安装（Windows 10/11）

建议 Python 3.11 或 3.12：

```powershell
cd AutoBard2
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[windows-fast]"
```

DXcam 当前版本的 `grab/start/get_latest_frame` 可以直接返回 NumPy 图像；本项目连续捕获时使用固定长度缓冲区，并始终消费最新帧。没有安装 DXcam 时会回退到持久化的 MSS 对象。

## 第一次使用：重新校准位置

1. 启动游戏并进入能显示演奏条的画面。
2. 运行：

```powershell
autobard --config config/settings.json calibrate --output config/settings.json
```

3. 第一个窗口：框住**完整演奏区域**，包含横向音符条以及移动指针。
4. 第二个窗口：在刚才的区域内，紧贴框住**音符所在的窄条**。
5. 程序会保存归一化坐标，并生成 `config/calibration_preview.jpg`。

校准坐标相对于游戏窗口客户区，因此窗口移动或分辨率变化后仍能跟随；改变画面比例、HUD 缩放或 UI 布局后应重新校准。

## 先用 dry-run 验证

`config/settings.json` 默认：

```json
"action": {
  "mode": "dry_run"
}
```

启动服务：

```powershell
autobard --config config/settings.json run
```

- `F8`：开始一次检测
- `F9`：中止当前检测
- `F10`：退出程序

建议先手动开始演奏，再按 `F8`。命中结果只写日志，不会发输入。每次运行的调试文件在：

```text
debug_output/YYYYMMDD_HHMMSS_xxxxxx/
├── initial_capture.jpg
├── note_mask.png
├── notes_overlay.jpg
└── tracking.csv
```

## 截图离线检查

将当前演奏画面截图后运行：

```powershell
autobard --config config/settings.json inspect-image your_capture.png --output debug_output/inspect.jpg
```

输入图片应当是校准后的完整 ROI；也可以尝试 `--auto-locate`，但自动定位只是候选建议，HUD 变化较大时仍以手动校准为准。

## 录像离线分析

推荐先录制几段当前版本游戏画面，再离线调参。完整屏幕录像会按 `capture.roi_normalized` 裁剪：

```powershell
autobard --config config/settings.json analyze-video performance.mp4 --output-dir debug_output/offline --start-s 0
```

录像本身已经只包含演奏 ROI 时，加 `--roi-is-frame`。输出包括带标记的 `offline_overlay.mp4` 和逐帧 `offline_tracking.csv`，该命令永远不会发送键鼠输入。

## 动作模式

### 1. dry_run（默认）

只输出预计命中时刻，最适合调试。

### 2. beep

```json
"action": {"mode": "beep"}
```

命中时短促提示音，适合验证时序。

### 3. system_input

系统输入模块使用 Windows `SendInput`，支持右键或普通键：

```json
"action": {
  "mode": "system_input",
  "kind": "mouse_right",
  "key": "space",
  "press_duration_ms": 8,
  "acknowledge_online_risk": true
}
```

使用键盘时把 `kind` 改成 `key`。该模式默认锁定，必须显式确认风险；它不保证目标游戏接受输入，也不会尝试绕过任何保护机制。

## 最常调的参数

### 音符漏检或多检

```json
"vision": {
  "notes": {
    "pixel_quantile": 0.76,
    "column_coverage": 0.20,
    "min_width_ratio": 0.009,
    "max_width_ratio": 0.20
  }
}
```

- 漏检：稍微降低 `pixel_quantile` 或 `column_coverage`。
- 背景被误判：提高这两个值。
- 两个相邻音符合并：降低 `merge_gap_ratio`。

### 指针不稳定

```json
"vision": {
  "pointer": {
    "motion_weight": 0.48,
    "edge_weight": 0.30,
    "color_weight": 0.22,
    "prediction_weight": 0.45
  }
}
```

- 游戏颜色变化大：降低 `color_weight`，提高 `motion_weight`。
- 画面运动干扰大：提高 `prediction_weight`，并缩小 `prediction_sigma_ratio`。
- 初始几帧难找：适当提高 `edge_weight` 或重新校准更紧的 ROI。

### 命中整体偏早或偏晚

```json
"scheduler": {"input_latency_ms": 22}
```

- 实际命中偏晚：增大 `input_latency_ms`。
- 实际命中偏早：减小该值。

## 性能测试

```powershell
python scripts/benchmark_capture.py --backend dxcam --frames 500
python scripts/benchmark_capture.py --backend mss --frames 500
```

实际性能取决于游戏帧率、GPU、显示模式、ROI 大小和录屏/滤镜软件。不要在高频循环中开启逐帧图片保存；`save_every_n_frames=0` 表示关闭。

## 运行测试

```powershell
pip install -e ".[dev]"
pytest
```

## 已知限制

- 压缩包里只有旧版教程截图，没有当前游戏版本的无标注原始帧，因此默认阈值只能作为起点，首次运行必须校准并检查调试图。
- 自动定位只能寻找“画面下部、细长、水平、内部对比明显”的候选区域，不能保证跨所有 HUD 和语言设置准确。
- 指针如果不呈连续右移、被特效完全遮挡或画面采集不到，跟踪器会在超时后停止。
- 多显示器且游戏运行在非主显卡输出时，DXcam 可能需要指定输出；当前版本自动模式失败后会回退 MSS。
