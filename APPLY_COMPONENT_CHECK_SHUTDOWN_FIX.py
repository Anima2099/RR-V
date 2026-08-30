from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "ui" / "pages" / "theme_settings_page.py"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    print("RR-V component-check shutdown race fix")
    print("Makes the background update-check result safe when the Qt page is already closing.")
    print()

    try:
        original = TARGET.read_text(encoding="utf-8")
        updated = original

        if "import weakref\n" not in updated:
            updated = replace_once(
                updated,
                "from pathlib import Path\nimport threading\n",
                "from pathlib import Path\nimport threading\nimport weakref\n",
                "weakref import",
            )

        if "from shiboken6 import isValid\n" not in updated:
            updated = replace_once(
                updated,
                "from PySide6.QtWidgets import (\n",
                "from shiboken6 import isValid\n\nfrom PySide6.QtWidgets import (\n",
                "shiboken isValid import",
            )

        old_block = '''        def run() -> None:\n            try:\n                result = check_component_updates(force=force)\n            except Exception:\n                result = ComponentUpdateCheckResult(components=())\n            self.component_check_finished.emit(result, notify)\n\n        threading.Thread(target=run, daemon=True).start()\n'''
        new_block = '''        page_ref = weakref.ref(self)\n\n        def run() -> None:\n            try:\n                result = check_component_updates(force=force)\n            except Exception:\n                result = ComponentUpdateCheckResult(components=())\n\n            page = page_ref()\n            if page is None or not isValid(page):\n                return\n            try:\n                page.component_check_finished.emit(result, notify)\n            except RuntimeError:\n                # The Qt object can be deleted between isValid() and emit() while\n                # the application is shutting down. In that case there is no UI\n                # left to receive the result, so ending the daemon worker is safe.\n                return\n\n        threading.Thread(target=run, daemon=True).start()\n'''

        if old_block in updated:
            updated = replace_once(
                updated,
                old_block,
                new_block,
                "component check worker lifecycle",
            )
        elif "page_ref = weakref.ref(self)" in updated and "not isValid(page)" in updated:
            pass
        else:
            raise PatchError("component check worker is neither original nor known fixed form")

        if updated == original:
            print("Already fixed. No file changed.")
            return 0

        TARGET.write_text(updated, encoding="utf-8")
    except (OSError, PatchError) as exc:
        print(f"PATCH FAILED: {exc}")
        print("Stop here and share this output. Do not discard your existing local changes.")
        return 1

    print("Shutdown race fix applied successfully.")
    print("Changed: ui/pages/theme_settings_page.py")
    print("- background worker no longer holds a strong page reference")
    print("- verifies the Qt object before emitting the result")
    print("- safely ignores the tiny close-vs-emit race window")
    print()
    print("Next: run python main.py, close RR-V quickly after launch several times, and confirm")
    print("that 'Signal source has been deleted' no longer appears.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
