from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

from app.app_update import AppInstallerAsset
from app.constants import APP_VERSION
from app.http_client import download_https_file
from app.paths import RRV_LOCAL_DIR


InstallerProgress = Callable[[int, int], None]
RRV_UPDATE_DOWNLOAD_DIR = RRV_LOCAL_DIR / "updates"


@dataclass(slots=True, frozen=True)
class InstallerDownloadResult:
    ok: bool
    path: Path | None
    message: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().casefold()


def verify_installer_file(path: Path, asset: AppInstallerAsset) -> tuple[bool, str]:
    path = Path(path)
    if not path.is_file():
        return False, "다운로드한 Installer 파일을 찾지 못했습니다."

    try:
        actual_size = path.stat().st_size
    except OSError as error:
        return False, f"Installer 파일 크기를 확인하지 못했습니다: {error}"

    if actual_size <= 0:
        return False, "다운로드한 Installer 파일이 비어 있습니다."
    if asset.size > 0 and actual_size != asset.size:
        return (
            False,
            f"Installer 파일 크기가 GitHub Release 정보와 다릅니다. "
            f"({actual_size} / {asset.size} bytes)",
        )

    try:
        actual_sha256 = file_sha256(path)
    except OSError as error:
        return False, f"Installer SHA-256을 계산하지 못했습니다: {error}"

    expected_sha256 = str(asset.sha256 or "").strip().casefold()
    if not expected_sha256 or actual_sha256 != expected_sha256:
        return False, "Installer SHA-256 검증에 실패했습니다. 파일을 실행하지 않습니다."

    return True, "Installer SHA-256 검증을 통과했습니다."


def _cleanup_previous_installers(directory: Path, keep_name: str = "") -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    for candidate in directory.glob("RR-V_Setup_*.exe"):
        if keep_name and candidate.name.casefold() == keep_name.casefold():
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass

    for candidate in directory.glob("*.rrv-http-part"):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def download_verified_installer(
    asset: AppInstallerAsset,
    *,
    destination_dir: Path = RRV_UPDATE_DOWNLOAD_DIR,
    progress: InstallerProgress | None = None,
) -> InstallerDownloadResult:
    name = str(asset.name or "").strip()
    if (
        not name.casefold().startswith("rr-v_setup_")
        or not name.casefold().endswith(".exe")
        or "/" in name
        or "\\" in name
    ):
        return InstallerDownloadResult(False, None, "Installer 파일 이름이 올바르지 않습니다.")

    directory = Path(destination_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return InstallerDownloadResult(
            False,
            None,
            f"업데이트 임시 폴더를 만들지 못했습니다: {error}",
        )

    _cleanup_previous_installers(directory, keep_name=name)
    destination = directory / name
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        download_https_file(
            asset.url,
            destination,
            headers={"User-Agent": f"RR-V/{APP_VERSION}"},
            timeout=300.0,
            progress=progress,
        )
    except Exception as error:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        return InstallerDownloadResult(
            False,
            None,
            f"Installer 다운로드에 실패했습니다: {error}",
        )

    verified, verification_message = verify_installer_file(destination, asset)
    if not verified:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        return InstallerDownloadResult(False, None, verification_message)

    return InstallerDownloadResult(True, destination, verification_message)
