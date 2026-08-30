from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BUILD_RELEASE = ROOT / "BUILD_RELEASE.ps1"
SPEC = ROOT / "RR-V.spec"
CHECKLIST = ROOT / "PACKAGING_CHECKLIST.txt"
CONSTANTS = ROOT / "app" / "constants.py"
VERSION_INFO = ROOT / "RR-V.version_info.txt"
INSTALLER = ROOT / "installer" / "RR-V.iss"
EXPECTED_VERSION = "1.3.0"
EXPECTED_CHANNEL = "beta"


class PrepError(RuntimeError):
    pass


def _read(path: Path) -> str:
    if not path.is_file():
        raise PrepError(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise PrepError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _verify_version_sources() -> None:
    constants = _read(CONSTANTS)
    version_match = re.search(r'APP_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', constants)
    channel_match = re.search(r'APP_RELEASE_CHANNEL\s*=\s*"([^"]+)"', constants)
    if not version_match or version_match.group(1) != EXPECTED_VERSION:
        actual = version_match.group(1) if version_match else "unreadable"
        raise PrepError(f"app/constants.py APP_VERSION is {actual}, expected {EXPECTED_VERSION}")
    if not channel_match or channel_match.group(1) != EXPECTED_CHANNEL:
        actual = channel_match.group(1) if channel_match else "unreadable"
        raise PrepError(f"app/constants.py APP_RELEASE_CHANNEL is {actual}, expected {EXPECTED_CHANNEL}")

    version_info = _read(VERSION_INFO)
    required_version_info = (
        "filevers=(1, 3, 0, 0)",
        "prodvers=(1, 3, 0, 0)",
        "StringStruct('FileVersion', '1.3.0')",
        "StringStruct('ProductVersion', '1.3.0')",
    )
    missing = [item for item in required_version_info if item not in version_info]
    if missing:
        raise PrepError("RR-V.version_info.txt is not fully aligned with 1.3.0")

    installer = _read(INSTALLER)
    if '#define MyAppVersion "1.3.0"' not in installer:
        raise PrepError("installer/RR-V.iss MyAppVersion is not 1.3.0")


def _patch_build_release() -> bool:
    original = _read(BUILD_RELEASE)
    updated = original
    replacements = (
        (
            '    "RR-V 1.2.0 build license manifest",',
            '    "RR-V 1.3.0 build license manifest",',
            "build license manifest version",
        ),
        (
            '    throw ("External runtime tools must not be bundled in RR-V 1.2.0:`n" + ($BundledExternalTools -join "`n"))',
            '    throw ("External runtime tools must not be bundled in RR-V 1.3.0:`n" + ($BundledExternalTools -join "`n"))',
            "external tool policy build label",
        ),
        (
            'Write-Host "RR-V 1.2.0 onedir build is ready."',
            'Write-Host "RR-V 1.3.0 onedir build is ready."',
            "build completion version",
        ),
    )
    for old, new, label in replacements:
        updated = _replace_once(updated, old, new, label)
    if updated != original:
        BUILD_RELEASE.write_text(updated, encoding="utf-8")
        return True
    return False


def _patch_spec() -> bool:
    original = _read(SPEC)
    updated = _replace_once(
        original,
        "# RR-V 1.2.0 community beta · onedir packaging spec",
        "# RR-V 1.3.0 community beta · onedir packaging spec",
        "PyInstaller spec release heading",
    )
    if updated != original:
        SPEC.write_text(updated, encoding="utf-8")
        return True
    return False


def _patch_checklist() -> bool:
    original = _read(CHECKLIST)
    updated = original
    replacements = (
        (
            "RR-V 1.2.0 community beta release checklist",
            "RR-V 1.3.0 community beta release checklist",
            "checklist heading",
        ),
        (
            '[ ] app\\constants.py shows APP_VERSION = "1.2.0"',
            '[ ] app\\constants.py shows APP_VERSION = "1.3.0" and APP_RELEASE_CHANNEL = "beta"',
            "checklist constants version",
        ),
        (
            "[ ] RR-V.version_info.txt shows FileVersion/ProductVersion 1.2.0",
            "[ ] RR-V.version_info.txt shows FileVersion/ProductVersion 1.3.0",
            "checklist version-info version",
        ),
        (
            "[ ] Version display shows 1.2.0",
            "[ ] Version display shows 1.3.0",
            "checklist UI version",
        ),
        (
            "[ ] Sidebar Program Information sits directly above Version 1.2.0 in the lower app-info area",
            "[ ] Sidebar Program Information sits directly above Version 1.3.0 in the lower app-info area",
            "checklist sidebar version",
        ),
        (
            "[ ] Archive the exact RR-V 1.2.0 source commit, specs, build script, WPC lock, browser extension, final onedir build, and Installer",
            "[ ] Archive the exact RR-V 1.3.0 source commit, specs, build script, WPC lock, browser extension, final onedir build, and Installer",
            "checklist archive version",
        ),
    )
    for old, new, label in replacements:
        updated = _replace_once(updated, old, new, label)

    # This line is intentionally historical. The no-bundled-tools policy began in 1.2.0.
    if "External runtime tool policy (1.2.0+)" not in updated:
        raise PrepError("Historical 1.2.0+ external runtime tool policy marker was unexpectedly changed")

    if updated != original:
        CHECKLIST.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> int:
    print("RR-V 1.3.0 build preparation")
    print("Aligns release metadata/checklist only; product behavior is not changed.")
    print()

    try:
        _verify_version_sources()
        changed = []
        if _patch_build_release():
            changed.append("BUILD_RELEASE.ps1")
        if _patch_spec():
            changed.append("RR-V.spec")
        if _patch_checklist():
            changed.append("PACKAGING_CHECKLIST.txt")
        _verify_version_sources()
    except (OSError, PrepError) as exc:
        print(f"BUILD PREP FAILED: {exc}")
        print("Stop here and share this output before building.")
        return 1

    print("Version sources verified:")
    print("- app/constants.py: 1.3.0 beta")
    print("- RR-V.version_info.txt: 1.3.0")
    print("- installer/RR-V.iss: 1.3.0")
    if changed:
        print("Updated build metadata:")
        for path in changed:
            print(f"- {path}")
    else:
        print("Build metadata was already prepared.")

    print()
    print("Next release-prep checkpoint:")
    print("1. python -m unittest discover -s tests -v")
    print("2. Review and commit the tested local changes in GitHub Desktop.")
    print("3. powershell -ExecutionPolicy Bypass -File .\\PREP_WPC_PROVIDER.ps1")
    print("4. powershell -ExecutionPolicy Bypass -File .\\BUILD_RELEASE.ps1")
    print("5. powershell -ExecutionPolicy Bypass -File .\\BUILD_INSTALLER.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
