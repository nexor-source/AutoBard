from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH)
hidden_imports = [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "mss.windows",
]
try:
    hidden_imports += collect_submodules("dxcam")
except Exception:
    pass

analysis = Analysis(
    [str(project_root / "src" / "autobard" / "gui_entry.py")],
    pathex=[str(project_root / "src")],
    binaries=[(str(project_root / "runtime" / "viiper.exe"), "runtime")],
    datas=[
        (str(project_root / "config" / "settings.json"), "config"),
        (str(project_root / "README.md"), "."),
        (str(project_root / "LICENSE"), "."),
        (str(project_root / "CHANGELOG.md"), "."),
        (str(project_root / "DISTRIBUTION.md"), "."),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AutoBard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    contents_directory=".",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoBard",
)
