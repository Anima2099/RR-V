from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
TARGETS = (
    (ROOT / "ui" / "tools" / "thumbnail_page.py", "details_button", "thumbnailStatusDetailsButton"),
    (ROOT / "ui" / "tools" / "snapshot_page.py", "status_details_button", "snapshotStatusDetailsButton"),
    (ROOT / "ui" / "tools" / "subtitle_page.py", "status_details_button", "subtitleStatusDetailsButton"),
)
SLOW_STATUS_GLYPHS = ("✓", "✕", "⚠")
ALL_MEASURED_BOMBS = ("↻", "▾", "▴", "✓", "✕", "⚠")


class PatchError(RuntimeError):
    pass


def _ensure_qsize_import(text: str, label: str) -> str:
    if re.search(r"from PySide6\.QtCore import [^\n]*\bQSize\b", text):
        return text
    match = re.search(r"from PySide6\.QtCore import ([^\n]+)", text)
    if not match:
        raise PatchError(f"{label}: QtCore import line not found")
    names = match.group(1)
    replacement = f"from PySide6.QtCore import QSize, {names}"
    return text[: match.start()] + replacement + text[match.end() :]


def _ensure_qicon_import(text: str, label: str) -> str:
    if re.search(r"\bQIcon\b", text):
        return text
    multiline = "from PySide6.QtGui import (\n"
    if multiline in text:
        return text.replace(multiline, multiline + "    QIcon,\n", 1)
    match = re.search(r"from PySide6\.QtGui import ([^\n]+)", text)
    if not match:
        raise PatchError(f"{label}: QtGui import line not found")
    names = match.group(1)
    replacement = f"from PySide6.QtGui import {names}, QIcon"
    return text[: match.start()] + replacement + text[match.end() :]


def _ensure_spin_imports(text: str, label: str) -> str:
    old = "from app.paths import RRV_LOGS_DIR"
    new = "from app.paths import RRV_LOGS_DIR, SPIN_DOWN_ICON_PATH, SPIN_UP_ICON_PATH"
    if "SPIN_DOWN_ICON_PATH" not in text:
        if old not in text:
            raise PatchError(f"{label}: app.paths import not found")
        text = text.replace(old, new, 1)
    if "from app.theme import themed_icon_path" not in text:
        marker = new if new in text else old
        text = text.replace(marker, marker + "\nfrom app.theme import themed_icon_path", 1)
    return text


def _patch_details_button(text: str, attr: str, object_name: str, label: str) -> str:
    original_init = f'        self.{attr} = QPushButton("자세히 ▾")\n        self.{attr}.setObjectName("{object_name}")'
    optimized_init = f'        self.{attr} = QPushButton("자세히")\n        self.{attr}.setObjectName("{object_name}")'

    if original_init in text:
        replacement = (
            optimized_init
            + f'\n        self.{attr}.setIcon(\n'
            + '            QIcon(str(themed_icon_path(SPIN_DOWN_ICON_PATH)))\n'
            + '        )\n'
            + f'        self.{attr}.setIconSize(QSize(12, 8))'
        )
        text = text.replace(original_init, replacement, 1)
    elif optimized_init in text and f"self.{attr}.setIcon(" in text:
        pass
    else:
        raise PatchError(f"{label}: details button is neither original nor known optimized form")

    toggle_pattern = re.compile(
        rf'(?P<indent>\s*)self\.{re.escape(attr)}\.setText\("자세히 ▴" if (?P<state>[A-Za-z_][A-Za-z0-9_]*) else "자세히 ▾"\)'
    )
    match = toggle_pattern.search(text)
    if match:
        indent = match.group("indent")
        state = match.group("state")
        replacement = (
            f'{indent}icon_path = SPIN_UP_ICON_PATH if {state} else SPIN_DOWN_ICON_PATH\n'
            f'{indent}self.{attr}.setIcon(QIcon(str(themed_icon_path(icon_path))))'
        )
        text = text[: match.start()] + replacement + text[match.end() :]
    elif "자세히 ▴" not in text and "자세히 ▾" not in text:
        pass
    else:
        raise PatchError(f"{label}: could not safely replace details toggle glyphs")

    return text


def _remove_slow_status_prefixes(text: str) -> tuple[str, int]:
    before = sum(text.count(glyph) for glyph in SLOW_STATUS_GLYPHS)
    for glyph in SLOW_STATUS_GLYPHS:
        text = text.replace(glyph + " ", "")
        text = text.replace(glyph, "")
    after = sum(text.count(glyph) for glyph in SLOW_STATUS_GLYPHS)
    return text, before - after


def _patch_file(path: Path, attr: str, object_name: str) -> tuple[bool, int]:
    label = path.name
    original = path.read_text(encoding="utf-8")
    updated = original

    if "자세히 ▾" in updated or f'self.{attr} = QPushButton("자세히")' in updated:
        updated = _ensure_qsize_import(updated, label)
        updated = _ensure_qicon_import(updated, label)
        updated = _ensure_spin_imports(updated, label)
        updated = _patch_details_button(updated, attr, object_name, label)

    updated, removed_status = _remove_slow_status_prefixes(updated)

    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True, removed_status
    return False, removed_status


def _remaining_bombs() -> list[str]:
    found: list[str] = []
    for path in sorted((ROOT / "ui").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = [glyph for glyph in ALL_MEASURED_BOMBS if glyph in text]
        if hits:
            found.append(f"{path.relative_to(ROOT)}: {' '.join(hits)}")
    return found


def main() -> int:
    print("RR-V remaining media glyph optimization")
    print("Measured slow glyphs only: detail arrows become SVG icons; slow status prefixes are removed.")
    print()

    changed = 0
    removed_status = 0
    try:
        for path, attr, object_name in TARGETS:
            file_changed, removed = _patch_file(path, attr, object_name)
            changed += int(file_changed)
            removed_status += removed
            state = "updated" if file_changed else "already optimized"
            print(f"{path.relative_to(ROOT)}: {state}, removed slow status glyphs={removed}")
    except (OSError, PatchError) as exc:
        print(f"PATCH FAILED: {exc}")
        print("Stop here and share this output. Do not commit partial changes yet.")
        return 1

    print()
    print(f"Changed media files: {changed}")
    print(f"Removed measured-slow status glyph occurrences: {removed_status}")

    remaining = _remaining_bombs()
    print()
    if remaining:
        print("Remaining measured-slow glyphs under ui/:")
        for item in remaining:
            print(f"- {item}")
        print("Share this list before release so the remaining occurrences can be reviewed.")
    else:
        print("No measured-slow glyphs remain under ui/.")

    print()
    print("Next:")
    print("1. python PROFILE_MEDIA_TOOLS_SIZEHINT_BREAKDOWN.py")
    print("2. python main.py")
    print("3. Compare media-tools sizeHint, startup.page.media_tools, and startup.main_window.total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
