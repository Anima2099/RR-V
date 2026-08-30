from __future__ import annotations

from pathlib import Path


TARGET = Path(__file__).resolve().parent / "ui" / "pages" / "download_page.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match, found {count}. "
            "No file was changed."
        )
    return text.replace(old, new, 1)


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    updated = original

    updated = replace_once(
        updated,
        "    FOLDER_ICON_PATH,\n)",
        "    FOLDER_ICON_PATH,\n    RETRY_ICON_PATH,\n)",
        "retry icon import",
    )

    updated = replace_once(
        updated,
        "        self.list_filter_bar = QWidget()\n        filter_row = QHBoxLayout(self.list_filter_bar)",
        "        self.list_filter_bar = QWidget()\n"
        "        # 빈 목록으로 시작할 때는 불필요한 초기 레이아웃 계산을 피한다.\n"
        "        self.list_filter_bar.setVisible(bool(self.tasks))\n"
        "        filter_row = QHBoxLayout(self.list_filter_bar)",
        "initial filter visibility",
    )

    updated = replace_once(
        updated,
        '        self.retry_all_failed_button = QPushButton("↻ 실패 작업 모두 재시도")\n'
        '        self.retry_all_failed_button.setObjectName("queueRetryButton")',
        '        self.retry_all_failed_button = QPushButton("실패 작업 모두 재시도")\n'
        '        self.retry_all_failed_button.setObjectName("queueRetryButton")\n'
        '        self.retry_all_failed_button.setIcon(QIcon(str(RETRY_ICON_PATH)))\n'
        '        self.retry_all_failed_button.setIconSize(QSize(18, 18))',
        "retry glyph replacement",
    )

    if updated == original:
        raise RuntimeError("No changes were produced. No file was changed.")

    TARGET.write_text(updated, encoding="utf-8")

    print("RR-V startup glyph fix applied successfully.")
    print("Changed: ui/pages/download_page.py")
    print("- removed the slow Unicode retry glyph")
    print("- reused resources/icons/retry.svg")
    print("- hides the empty filter bar before first attachment")
    print("Next: run python main.py and compare startup time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
