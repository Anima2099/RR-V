from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.general_preferences import load_general_preferences


def play_completion_sound() -> None:
    """설정이 켜져 있을 때 운영체제의 기본 알림음을 한 번 재생한다."""

    if not load_general_preferences().notify_completion_sound:
        return

    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return
        except (ImportError, RuntimeError, OSError):
            pass

    try:
        QApplication.beep()
    except RuntimeError:
        pass
