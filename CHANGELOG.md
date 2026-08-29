# Changelog

## 2.1.0

- Added a Windows GUI for service control, calibration, settings and logs.
- Added a PyInstaller onedir build containing VIIPER and the default configuration.
- Added SHA-256-verified GitHub Releases update checks and in-place Windows updates.
- Added a GitHub Actions workflow for producing versioned Windows release assets.
- Added public lifecycle controls to the hotkey service for GUI integration.

## 2.0.0

- Rebuilt the project as an installable Python package.
- Added DXcam-first capture with persistent MSS fallback.
- Added window-relative ROI calibration.
- Replaced absolute BGR matching with adaptive note detection.
- Added motion/edge/color pointer fusion and speed estimation.
- Added non-blocking, one-shot note scheduling.
- Added dry-run, beep and guarded Windows SendInput actions.
- Added screenshot inspection, offline video analysis and debug CSV/video output.
- Added synthetic tests for brightness variation, tracking and scheduling.
