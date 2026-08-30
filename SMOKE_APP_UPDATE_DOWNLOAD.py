from __future__ import annotations

import json
from pathlib import Path
import shutil

from app.app_update import RELEASES_API_URL, _installer_asset_from_release
from app.app_update_installer import download_verified_installer
from app.constants import APP_VERSION
from app.http_client import fetch_https_bytes
from app.paths import RRV_LOCAL_DIR


TARGET_TAG = "v1.2.0-community-beta"
SMOKE_DIR = RRV_LOCAL_DIR / "updates" / "smoke-test"


def _format_mb(value: int) -> str:
    return f"{max(0, value) / (1024 * 1024):.1f} MB"


def main() -> int:
    print("RR-V app update download smoke test")
    print(f"Current development version: {APP_VERSION}")
    print(f"Target release: {TARGET_TAG}")
    print("Installer execution: DISABLED")
    print()

    try:
        payload = json.loads(
            fetch_https_bytes(
                RELEASES_API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"RR-V/{APP_VERSION}-smoke-test",
                },
                timeout=20.0,
                max_bytes=2 * 1024 * 1024,
            ).decode("utf-8")
        )
    except Exception as error:
        print(f"SMOKE TEST: FAIL - release query failed: {error}")
        return 1

    if not isinstance(payload, list):
        print("SMOKE TEST: FAIL - GitHub Releases response is not a list.")
        return 1

    release = next(
        (
            item
            for item in payload
            if isinstance(item, dict)
            and str(item.get("tag_name") or "").strip() == TARGET_TAG
        ),
        None,
    )
    if release is None:
        print(f"SMOKE TEST: FAIL - release not found: {TARGET_TAG}")
        return 1

    print("[1/5] Release found")
    print(f"      {release.get('name') or TARGET_TAG}")

    asset = _installer_asset_from_release(release)
    if asset is None:
        print("SMOKE TEST: FAIL - verified Installer metadata was not found.")
        return 1

    print("[2/5] Installer metadata accepted")
    print(f"      File: {asset.name}")
    print(f"      Size: {asset.size} bytes ({_format_mb(asset.size)})")
    print(f"      SHA-256: {asset.sha256}")

    def progress(downloaded: int, total: int) -> None:
        if total > 0:
            percent = max(0, min(100, int(downloaded * 100 / total)))
            print(
                f"\r[3/5] Downloading: {percent:3d}% "
                f"({_format_mb(downloaded)} / {_format_mb(total)})",
                end="",
                flush=True,
            )
        else:
            print(
                f"\r[3/5] Downloading: {_format_mb(downloaded)}",
                end="",
                flush=True,
            )

    result = download_verified_installer(
        asset,
        destination_dir=SMOKE_DIR,
        progress=progress,
    )
    print()

    if not result.ok or result.path is None:
        print(f"SMOKE TEST: FAIL - {result.message}")
        shutil.rmtree(SMOKE_DIR, ignore_errors=True)
        return 1

    verified_path = Path(result.path)
    print("[4/5] Size and SHA-256 verification passed")
    print(f"      {result.message}")
    print(f"      Verified file: {verified_path}")
    print("      Installer execution: SKIPPED")

    try:
        verified_path.unlink(missing_ok=True)
        shutil.rmtree(SMOKE_DIR, ignore_errors=True)
    except OSError as error:
        print(f"SMOKE TEST: FAIL - verified test file cleanup failed: {error}")
        return 1

    print("[5/5] Verified test Installer deleted")
    print("SMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
