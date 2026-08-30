# -*- mode: python ; coding: utf-8 -*-
# RR-V 1.3.0 community beta · onedir packaging spec

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()
RESOURCES_DIR = PROJECT_ROOT / "resources"
ICONS_DIR = RESOURCES_DIR / "icons"
THEMES_DIR = RESOURCES_DIR / "themes"
WPC_PROVIDER_DIR = RESOURCES_DIR / "wpc-provider"
WPC_RUNTIME_DIR = WPC_PROVIDER_DIR / "runtime"
WPC_LOCK_FILE = WPC_PROVIDER_DIR / "WPC_RUNTIME_LOCK.txt"
BROWSER_EXTENSION_DIR = RESOURCES_DIR / "browser-extension" / "rrv-chromium"

LOCKED_WPC_DIST_INFO = (
    "yt_dlp_getpot_wpc-1.1.2.dist-info",
    "nodriver-0.50.3.dist-info",
    "mss-10.2.0.dist-info",
    "websockets-16.1.1.dist-info",
    "deprecated-1.3.1.dist-info",
    "wrapt-2.3.0.dist-info",
)

APP_ICON = ICONS_DIR / "RR-V.ico"
APP_PNG = ICONS_DIR / "RR-V.png"
THEME_FILE = THEMES_DIR / "warm_sage.qss"
VERSION_FILE = PROJECT_ROOT / "RR-V.version_info.txt"

REQUIRED_ICON_FILES = (
    "RR-V.ico",
    "RR-V.png",
    "close.svg",
    "collapse.svg",
    "copy.svg",
    "drag.svg",
    "expand.svg",
    "folder.svg",
    "more.svg",
    "retry.svg",
    "spin_down.svg",
    "spin_up.svg",
    "stop.svg",
)

required_files = [
    THEME_FILE,
    VERSION_FILE,
    WPC_RUNTIME_DIR / "yt_dlp_plugins" / "extractor" / "getpot_wpc.py",
    WPC_RUNTIME_DIR / "nodriver" / "__init__.py",
    WPC_LOCK_FILE,
]
required_files.extend(WPC_RUNTIME_DIR / name / "METADATA" for name in LOCKED_WPC_DIST_INFO)
required_files.extend(ICONS_DIR / name for name in REQUIRED_ICON_FILES)
BROWSER_EXTENSION_FILES = (
    "manifest.json",
    "background.js",
    "RR-V.png",
    "README.txt",
)
required_files.extend(
    BROWSER_EXTENSION_DIR / name
    for name in BROWSER_EXTENSION_FILES
)

missing = [path for path in required_files if not path.is_file()]
if missing:
    formatted = "\n".join(f"  - {path.relative_to(PROJECT_ROOT)}" for path in missing)
    raise SystemExit(
        "RR-V 패키징에 필요한 파일이 없습니다. 아래 파일을 준비한 뒤 다시 빌드하세요:\n"
        + formatted
    )

actual_dist_info = {path.name for path in WPC_RUNTIME_DIR.glob("*.dist-info") if path.is_dir()}
expected_dist_info = set(LOCKED_WPC_DIST_INFO)
if actual_dist_info != expected_dist_info:
    raise SystemExit(
        "RR-V WPC 런타임 버전 구성이 잠금 목록과 다릅니다. "
        "PREP_WPC_PROVIDER.ps1을 다시 실행하세요.\n"
        f"Expected: {sorted(expected_dist_info)}\n"
        f"Actual: {sorted(actual_dist_info)}"
    )

wpc_cache_files = list(WPC_RUNTIME_DIR.rglob("*.pyc"))
wpc_cache_dirs = [path for path in WPC_RUNTIME_DIR.rglob("__pycache__") if path.is_dir()]
if wpc_cache_files or wpc_cache_dirs:
    raise SystemExit(
        "WPC 배포 런타임에 __pycache__ 또는 .pyc가 남아 있습니다. "
        "PREP_WPC_PROVIDER.ps1을 다시 실행하세요."
    )

# 외부 실행 도구(yt-dlp/FFmpeg/FFprobe/Deno)는 1.2.0부터 번들하지 않는다.
# 사용자가 RR-V 실행 후 도구 및 리소스 화면에서 각 공식 배포처로부터 설치한다.
datas = [
    (str(THEME_FILE), "resources/themes"),
]
datas.extend((str(ICONS_DIR / name), "resources/icons") for name in REQUIRED_ICON_FILES)
datas.append((str(WPC_PROVIDER_DIR), "resources/wpc-provider"))
datas.extend(
    (str(BROWSER_EXTENSION_DIR / name), "resources/browser-extension/rrv-chromium")
    for name in BROWSER_EXTENSION_FILES
)

# RR-V는 로컬 단일 실행/URL 전달에 QtNetwork를 사용한다. QtSvg와 함께
# onedir 환경에서 명시적으로 포함한다.
hiddenimports = [
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
]

# 다른 Qt 바인딩이 설치되어 있어도 RR-V에는 PySide6만 사용한다.
excludes = [
    "PyQt5",
    "PyQt6",
    "PySide2",
]

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Qt 6.11의 Qt Virtual Keyboard는 community 배포에서 GPLv3 전용 모듈이다.
# RR-V는 이 기능을 사용하지 않지만 PyInstaller의 Qt plugin 수집 과정에서
# DLL/plugin이 따라올 수 있으므로 release TOC에서 명시적으로 제외한다.
# 나머지 RR-V가 사용하는 Qt shared libraries는 LGPLv3 조건으로 배포한다.
def keep_release_binary(entry):
    destination = str(entry[0]).replace("\\", "/").lower()
    blocked_suffixes = (
        "pyside6/qt6virtualkeyboard.dll",
        "pyside6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    )
    return not any(destination.endswith(suffix) for suffix in blocked_suffixes)


a.binaries = [entry for entry in a.binaries if keep_release_binary(entry)]

pyz = PYZ(a.pure)

# onedir: Python/Qt DLL과 리소스는 dist/RR-V/_internal 아래에 분리되고,
# 사용자가 실행하는 RR-V.exe는 dist/RR-V 루트에 남는다.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RR-V",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(APP_ICON),
    version=str(VERSION_FILE),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RR-V",
)
