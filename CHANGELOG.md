# Changelog

## 2.1.1

- Improve cursor detection by following the calibrated note exclusion band and keeping prediction separate from visual confidence and position.
- Increase the default speed-fit window to 90 samples and the session timeout to 12 seconds; preserve the double-right-click trigger and intentional first-note skip.
- Include raw event screenshots, configuration snapshots and session end reasons for diagnostics.
- Migrate preserved legacy configurations on first launch: upgrade the old 18-sample speed window to 90 and the old 8-second session limit to 12 seconds.
- Back up the original configuration before migration, preserve calibration and other settings, and keep non-default values and later user changes.
- Save configuration files atomically; read-only installations still use migrated values for the current run.
- Package a clean first-install configuration independently of local calibration and debug settings.

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
