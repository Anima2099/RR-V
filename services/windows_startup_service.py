from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "RR-V"
_STARTUP_HIDDEN_FLAG = "--startup-hidden"


class WindowsStartupError(RuntimeError):
    pass


def is_windows_startup_supported() -> bool:
    return os.name == "nt"


def build_startup_command(*, start_hidden: bool) -> str:
    """현재 RR-V 실행 위치를 기준으로 Windows 자동 실행 명령을 만든다."""
    if getattr(sys, "frozen", False):
        arguments = [str(Path(sys.executable).resolve())]
    else:
        python_executable = Path(sys.executable).resolve()
        pythonw = python_executable.with_name("pythonw.exe")
        if os.name == "nt" and pythonw.is_file():
            python_executable = pythonw
        main_path = Path(__file__).resolve().parent.parent / "main.py"
        arguments = [str(python_executable), str(main_path.resolve())]

    if start_hidden:
        arguments.append(_STARTUP_HIDDEN_FLAG)
    return subprocess.list2cmdline(arguments)


def _read_registered_command() -> str | None:
    if not is_windows_startup_supported():
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, value_type = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise WindowsStartupError(str(error)) from error

    if value_type not in {winreg.REG_SZ, winreg.REG_EXPAND_SZ}:
        return None
    return str(value)


def set_windows_startup_enabled(
    enabled: bool,
    *,
    start_hidden: bool,
) -> None:
    """현재 사용자(HKCU)의 Windows 시작 프로그램 등록을 맞춘다."""
    if not is_windows_startup_supported():
        if enabled:
            raise WindowsStartupError("Windows에서만 자동 실행을 사용할 수 있습니다.")
        return

    try:
        import winreg

        if enabled:
            command = build_startup_command(start_hidden=start_hidden)
            current = _read_registered_command()
            if current == command:
                return
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                _RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    _RUN_VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    command,
                )
            return

        current = _read_registered_command()
        if current is None:
            return
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, _RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    except WindowsStartupError:
        raise
    except OSError as error:
        raise WindowsStartupError(str(error)) from error


def sync_windows_startup_registration(
    enabled: bool,
    *,
    start_hidden: bool,
) -> None:
    """설정값과 실제 Run 등록을 일치시킨다."""
    set_windows_startup_enabled(enabled, start_hidden=start_hidden)
