# -*- mode: python ; coding: utf-8 -*-
# RR-V Auth Helper 1.2.0
#
# This executable intentionally contains only the helper code and Python runtime.
# nodriver itself is loaded at runtime from RR-V's WPC runtime directory so the
# helper remains a separate process/component from the RR-V core application.

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()
APP_ICON = PROJECT_ROOT / "resources" / "icons" / "RR-V.ico"

if not APP_ICON.is_file():
    raise SystemExit(f"RR-V Auth Helper icon is missing: {APP_ICON}")

# Keep the helper small and independent from the Qt GUI application.
excludes = [
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
]

a = Analysis(
    [str(PROJECT_ROOT / "auth_helper" / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# console=True is intentional. RR-V starts this executable with CREATE_NO_WINDOW
# and reads its stdout pipe as UTF-8 JSON-lines. A window is therefore not shown
# to the user, while stdout remains available for the IPC protocol.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RR-V-Auth-Helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(APP_ICON),
)
