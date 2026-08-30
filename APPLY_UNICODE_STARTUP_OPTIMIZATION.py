from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
DOWNLOAD_PAGE = ROOT / "ui" / "pages" / "download_page.py"
CONVERTER_PAGE = ROOT / "ui" / "tools" / "converter_page.py"
SETTINGS_FILES = tuple(sorted((ROOT / "ui" / "pages").glob("*settings*.py")))


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_download_page() -> tuple[bool, str]:
    original = DOWNLOAD_PAGE.read_text(encoding="utf-8")
    updated = original

    slow_text = 'self.retry_all_failed_button = QPushButton("↻ 실패 작업 모두 재시도")'
    optimized_text = 'self.retry_all_failed_button = QPushButton("실패 작업 모두 재시도")'

    if slow_text in updated:
        if "    RETRY_ICON_PATH,\n" not in updated:
            updated = replace_once(
                updated,
                "    FOLDER_ICON_PATH,\n)",
                "    FOLDER_ICON_PATH,\n    RETRY_ICON_PATH,\n)",
                "download retry icon import",
            )

        visibility_line = "        self.list_filter_bar.setVisible(bool(self.tasks))\n"
        if visibility_line not in updated:
            updated = replace_once(
                updated,
                "        self.list_filter_bar = QWidget()\n",
                "        self.list_filter_bar = QWidget()\n"
                "        # 빈 목록으로 시작할 때는 불필요한 초기 레이아웃 계산을 피한다.\n"
                "        self.list_filter_bar.setVisible(bool(self.tasks))\n",
                "download initial filter visibility",
            )

        updated = replace_once(
            updated,
            '        self.retry_all_failed_button = QPushButton("↻ 실패 작업 모두 재시도")\n'
            '        self.retry_all_failed_button.setObjectName("queueRetryButton")',
            '        self.retry_all_failed_button = QPushButton("실패 작업 모두 재시도")\n'
            '        self.retry_all_failed_button.setObjectName("queueRetryButton")\n'
            '        self.retry_all_failed_button.setIcon(QIcon(str(RETRY_ICON_PATH)))\n'
            '        self.retry_all_failed_button.setIconSize(QSize(18, 18))',
            "download retry glyph replacement",
        )
    elif optimized_text in updated and "setIcon(QIcon(str(RETRY_ICON_PATH)))" in updated:
        # The earlier focused patch has already optimized this local file.
        pass
    else:
        raise PatchError("download page: retry button is neither original nor known optimized form")

    if updated != original:
        DOWNLOAD_PAGE.write_text(updated, encoding="utf-8")
        return True, "download: replaced ↻ with retry.svg and preserved empty-list fast path"
    return False, "download: already optimized"


def patch_converter_page() -> tuple[bool, str]:
    original = CONVERTER_PAGE.read_text(encoding="utf-8")
    updated = original

    if 'QPushButton("자세히 ▾")' in updated:
        updated = replace_once(
            updated,
            "from PySide6.QtCore import QTimer, Qt, QUrl, Signal",
            "from PySide6.QtCore import QSize, QTimer, Qt, QUrl, Signal",
            "converter QSize import",
        )
        updated = replace_once(
            updated,
            "from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent",
            "from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QIcon",
            "converter QIcon import",
        )
        updated = replace_once(
            updated,
            "from app.paths import RRV_LOGS_DIR",
            "from app.paths import RRV_LOGS_DIR, SPIN_DOWN_ICON_PATH, SPIN_UP_ICON_PATH",
            "converter spin icon paths",
        )
        updated = replace_once(
            updated,
            "from core.converter_models import ConversionOptions, VideoProbeResult",
            "from core.converter_models import ConversionOptions, VideoProbeResult\nfrom app.theme import themed_icon_path",
            "converter themed icon helper",
        )
        updated = replace_once(
            updated,
            '        self.details_button = QPushButton("자세히 ▾")\n'
            '        self.details_button.setObjectName("converterStatusDetailsButton")',
            '        self.details_button = QPushButton("자세히")\n'
            '        self.details_button.setObjectName("converterStatusDetailsButton")\n'
            '        self.details_button.setIcon(\n'
            '            QIcon(str(themed_icon_path(SPIN_DOWN_ICON_PATH)))\n'
            '        )\n'
            '        self.details_button.setIconSize(QSize(12, 8))',
            "converter details down glyph",
        )
        updated = replace_once(
            updated,
            '        self.details_button.setText("자세히 ▴" if expanded else "자세히 ▾")',
            '        icon_path = SPIN_UP_ICON_PATH if expanded else SPIN_DOWN_ICON_PATH\n'
            '        self.details_button.setIcon(QIcon(str(themed_icon_path(icon_path))))',
            "converter details toggle glyphs",
        )
    elif 'self.details_button = QPushButton("자세히")' in updated and "SPIN_DOWN_ICON_PATH" in updated:
        pass
    else:
        raise PatchError("converter page: details button is neither original nor known optimized form")

    if updated != original:
        CONVERTER_PAGE.write_text(updated, encoding="utf-8")
        return True, "media tools: replaced ▾/▴ text glyphs with preloaded spin SVG icons"
    return False, "media tools: already optimized"


def patch_settings_pages() -> tuple[int, int]:
    changed_files = 0
    removed_glyphs = 0
    for path in SETTINGS_FILES:
        original = path.read_text(encoding="utf-8")
        updated = original
        before = sum(updated.count(glyph) for glyph in ("✓", "✕", "⚠"))
        if before:
            # These are decorative status prefixes. Their Korean text already carries
            # the complete meaning, so removing the glyph preserves the information.
            for glyph in ("✓", "✕", "⚠"):
                updated = updated.replace(glyph + " ", "")
                updated = updated.replace(glyph, "")
        after = sum(updated.count(glyph) for glyph in ("✓", "✕", "⚠"))
        removed_glyphs += before - after
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed_files += 1
    return changed_files, removed_glyphs


def remaining_bombs() -> list[str]:
    found: list[str] = []
    for path in sorted((ROOT / "ui").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = [glyph for glyph in ("↻", "▾", "▴", "✓", "✕", "⚠") if glyph in text]
        if hits:
            found.append(f"{path.relative_to(ROOT)}: {' '.join(hits)}")
    return found


def main() -> int:
    print("RR-V Unicode startup optimization")
    print("Only measured slow decorative glyphs are changed.")
    print()

    try:
        download_changed, download_message = patch_download_page()
        converter_changed, converter_message = patch_converter_page()
        settings_changed, settings_removed = patch_settings_pages()
    except (OSError, PatchError) as exc:
        print(f"PATCH FAILED: {exc}")
        print("Stop here and share this output. Do not commit partial changes yet.")
        return 1

    print(download_message)
    print(converter_message)
    print(
        f"settings: removed {settings_removed} slow status glyph occurrences "
        f"across {settings_changed} file(s)"
    )

    remaining = remaining_bombs()
    print()
    if remaining:
        print("Remaining measured-slow glyphs under ui/ (review before release):")
        for item in remaining:
            print(f"- {item}")
    else:
        print("No measured-slow decorative glyphs remain under ui/.")

    print()
    print("Next:")
    print("1. python main.py")
    print("2. Compare startup.page.download, startup.page.media_tools, startup.page.settings,")
    print("   and startup.main_window.total.")
    print("3. If the timing is clean, run the normal test suite before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
