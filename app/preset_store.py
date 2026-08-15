from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from app.download_preferences import (
    LEGACY_PRESET_NAMES,
    DownloadPreferences,
    load_legacy_download_preferences,
    save_legacy_download_preferences,
)
from app.paths import PRESETS_BACKUP_PATH, PRESETS_PATH


PRESET_FILE_FORMAT = "RR-V-download-presets"
PRESET_FILE_VERSION = 1


@dataclass(slots=True, frozen=True)
class DownloadPreset:
    preset_id: str
    name: str
    resolution: str = "최고 화질"
    container: str = "MP4"
    codec: str = "H.264"
    receive_subtitles: bool = True
    preferred_subtitles: tuple[str, ...] = ("ko",)
    allow_automatic_subtitles: bool = True
    embed_subtitles: bool = True
    embed_thumbnail: bool = False
    save_thumbnail: bool = False
    preserve_metadata: bool = True
    audio_only: bool = False
    audio_format: str = "M4A"
    audio_quality: str = "최고"

    @classmethod
    def from_preferences(
        cls,
        name: str,
        preferences: DownloadPreferences,
        *,
        preset_id: str | None = None,
    ) -> "DownloadPreset":
        p = preferences.normalized()
        return cls(
            preset_id=(preset_id or str(uuid4())).strip(),
            name=name.strip() or "새 프리셋",
            resolution=p.resolution,
            container=p.container,
            codec=p.codec,
            receive_subtitles=p.receive_subtitles and not p.audio_only,
            preferred_subtitles=tuple(p.preferred_subtitles),
            allow_automatic_subtitles=p.allow_automatic_subtitles,
            embed_subtitles=p.embed_subtitles and not p.audio_only,
            embed_thumbnail=p.embed_thumbnail,
            save_thumbnail=p.save_thumbnail,
            preserve_metadata=p.preserve_metadata,
            audio_only=p.audio_only,
            audio_format=p.audio_format,
            audio_quality=p.audio_quality,
        )

    def to_preferences(self) -> DownloadPreferences:
        return DownloadPreferences(
            preset_id=self.preset_id,
            preset=self.name,
            resolution=self.resolution,
            container=self.container,
            codec=self.codec,
            receive_subtitles=self.receive_subtitles,
            preferred_subtitles=tuple(self.preferred_subtitles),
            allow_automatic_subtitles=self.allow_automatic_subtitles,
            embed_subtitles=self.embed_subtitles,
            embed_thumbnail=self.embed_thumbnail,
            save_thumbnail=self.save_thumbnail,
            preserve_metadata=self.preserve_metadata,
            audio_only=self.audio_only,
            audio_format=self.audio_format,
            audio_quality=self.audio_quality,
        ).normalized()

    def with_preferences(self, preferences: DownloadPreferences) -> "DownloadPreset":
        return DownloadPreset.from_preferences(
            self.name,
            preferences,
            preset_id=self.preset_id,
        )

    def renamed(self, name: str) -> "DownloadPreset":
        return DownloadPreset.from_preferences(
            name,
            self.to_preferences(),
            preset_id=self.preset_id,
        )

    def duplicate(self, name: str) -> "DownloadPreset":
        return DownloadPreset.from_preferences(name, self.to_preferences())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = data.pop("preset_id")
        data["preferred_subtitles"] = list(self.preferred_subtitles)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DownloadPreset":
        preset_id = str(raw.get("id", raw.get("preset_id", ""))).strip()
        name = str(raw.get("name", "")).strip()
        if not preset_id or not name:
            raise ValueError("프리셋 ID 또는 이름이 비어 있습니다.")

        preferred_raw = raw.get("preferred_subtitles", ["ko"])
        if isinstance(preferred_raw, str):
            preferred = tuple(
                item.strip().lower()
                for item in preferred_raw.split(",")
                if item.strip()
            )
        elif isinstance(preferred_raw, (list, tuple)):
            preferred = tuple(str(item).strip().lower() for item in preferred_raw if str(item).strip())
        else:
            preferred = ("ko",)

        def bool_value(key: str, default: bool) -> bool:
            value = raw.get(key, default)
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}

        preferences = DownloadPreferences(
            preset_id=preset_id,
            preset=name,
            resolution=str(raw.get("resolution", "최고 화질")),
            container=str(raw.get("container", "MP4")),
            codec=str(raw.get("codec", "H.264")),
            receive_subtitles=bool_value("receive_subtitles", True),
            preferred_subtitles=preferred,
            allow_automatic_subtitles=bool_value("allow_automatic_subtitles", True),
            embed_subtitles=bool_value("embed_subtitles", True),
            embed_thumbnail=bool_value("embed_thumbnail", False),
            save_thumbnail=bool_value("save_thumbnail", False),
            preserve_metadata=bool_value("preserve_metadata", True),
            audio_only=bool_value("audio_only", False),
            audio_format=str(raw.get("audio_format", "M4A")),
            audio_quality=str(raw.get("audio_quality", "최고")),
        ).normalized()
        return cls.from_preferences(name, preferences, preset_id=preset_id)


@dataclass(slots=True)
class PresetLibrary:
    presets: list[DownloadPreset] = field(default_factory=list)
    default_preset_id: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.presets:
            raise ValueError("프리셋은 최소 한 개가 필요합니다.")

        ids: set[str] = set()
        names: set[str] = set()
        for preset in self.presets:
            if preset.preset_id in ids:
                raise ValueError("중복된 프리셋 ID가 있습니다.")
            folded = preset.name.casefold()
            if folded in names:
                raise ValueError("중복된 프리셋 이름이 있습니다.")
            ids.add(preset.preset_id)
            names.add(folded)

        if self.default_preset_id not in ids:
            self.default_preset_id = self.presets[0].preset_id

    @property
    def default_preset(self) -> DownloadPreset:
        return self.get(self.default_preset_id) or self.presets[0]

    def get(self, preset_id: str) -> DownloadPreset | None:
        return next(
            (preset for preset in self.presets if preset.preset_id == preset_id),
            None,
        )

    def get_by_name(self, name: str) -> DownloadPreset | None:
        target = name.strip().casefold()
        return next(
            (preset for preset in self.presets if preset.name.casefold() == target),
            None,
        )

    def has_name(self, name: str, *, exclude_id: str = "") -> bool:
        target = name.strip().casefold()
        return any(
            preset.preset_id != exclude_id and preset.name.casefold() == target
            for preset in self.presets
        )

    def add_preset(self, preset: DownloadPreset) -> None:
        if self.get(preset.preset_id) is not None:
            raise ValueError("이미 존재하는 프리셋 ID입니다.")
        if self.has_name(preset.name):
            raise ValueError("같은 이름의 프리셋이 이미 있습니다.")
        self.presets.append(preset)
        self._validate()

    def replace_preset(self, preset_id: str, replacement: DownloadPreset) -> None:
        if replacement.preset_id != preset_id:
            raise ValueError("프리셋 ID는 변경할 수 없습니다.")
        if self.has_name(replacement.name, exclude_id=preset_id):
            raise ValueError("같은 이름의 프리셋이 이미 있습니다.")
        for index, preset in enumerate(self.presets):
            if preset.preset_id == preset_id:
                self.presets[index] = replacement
                self._validate()
                return
        raise KeyError("프리셋을 찾을 수 없습니다.")

    def remove_preset(self, preset_id: str) -> DownloadPreset:
        if len(self.presets) <= 1:
            raise ValueError("마지막 프리셋은 삭제할 수 없습니다.")
        if preset_id == self.default_preset_id:
            raise ValueError("기본 프리셋은 먼저 다른 프리셋으로 변경해야 합니다.")
        for index, preset in enumerate(self.presets):
            if preset.preset_id == preset_id:
                removed = self.presets.pop(index)
                self._validate()
                return removed
        raise KeyError("프리셋을 찾을 수 없습니다.")

    def set_default(self, preset_id: str) -> None:
        if self.get(preset_id) is None:
            raise KeyError("프리셋을 찾을 수 없습니다.")
        self.default_preset_id = preset_id

    def to_payload(self) -> dict[str, Any]:
        self._validate()
        return {
            "format": PRESET_FILE_FORMAT,
            "version": PRESET_FILE_VERSION,
            "default_preset_id": self.default_preset_id,
            "presets": [preset.to_dict() for preset in self.presets],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PresetLibrary":
        if payload.get("format") != PRESET_FILE_FORMAT:
            raise ValueError("RR-V 다운로드 프리셋 파일이 아닙니다.")
        if int(payload.get("version", 0)) != PRESET_FILE_VERSION:
            raise ValueError("지원하지 않는 다운로드 프리셋 버전입니다.")
        raw_presets = payload.get("presets")
        if not isinstance(raw_presets, list):
            raise ValueError("프리셋 목록 형식이 올바르지 않습니다.")
        presets = [
            DownloadPreset.from_dict(raw)
            for raw in raw_presets
            if isinstance(raw, dict)
        ]
        return cls(
            presets=presets,
            default_preset_id=str(payload.get("default_preset_id", "")).strip(),
        )


def _create_initial_library() -> PresetLibrary:
    legacy = load_legacy_download_preferences()
    presets: list[DownloadPreset] = []
    default_id = ""

    for name in LEGACY_PRESET_NAMES:
        # 1.0.x에서 선택한 프리셋을 사용자가 다시 손으로 조정해 저장했을 수
        # 있으므로 현재 선택본 하나는 settings.ini의 실제 값을 그대로 보존한다.
        # 나머지 예제 프리셋만 기존 하드코딩 정의로 생성한다.
        preferences = (
            legacy
            if name == legacy.preset
            else legacy.with_legacy_preset(name)
        )
        preset = DownloadPreset.from_preferences(name, preferences)
        presets.append(preset)
        if name == legacy.preset:
            default_id = preset.preset_id

    # 1.1.0에서 settings.ini에 남긴 복구용 거울값일 수 있다. JSON과 백업이
    # 모두 사라진 경우에도 사용자 기본 프리셋의 이름과 정확한 옵션은 살린다.
    if legacy.preset not in LEGACY_PRESET_NAMES:
        recovered = DownloadPreset.from_preferences(legacy.preset, legacy)
        presets.append(recovered)
        default_id = recovered.preset_id

    return PresetLibrary(
        presets=presets,
        default_preset_id=default_id or presets[0].preset_id,
    )


def _read_library(path: Path) -> PresetLibrary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("프리셋 파일의 최상위 형식이 올바르지 않습니다.")
    return PresetLibrary.from_payload(payload)


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        # 실제 교체 전에 임시 파일을 다시 읽어 JSON 구조를 검증한다.
        parsed = json.loads(temp_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise OSError("다운로드 프리셋 임시 파일 검증에 실패했습니다.")
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _mirror_primary_to_backup() -> None:
    if not PRESETS_PATH.is_file():
        return
    PRESETS_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PRESETS_PATH, PRESETS_BACKUP_PATH)


def _archive_corrupt(path: Path) -> None:
    if not path.is_file():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = path.with_name(f"{path.stem}.corrupt_{stamp}{path.suffix}")
    try:
        path.replace(destination)
    except OSError:
        pass


def load_preset_library() -> PresetLibrary:
    if PRESETS_PATH.is_file():
        try:
            return _read_library(PRESETS_PATH)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            if PRESETS_BACKUP_PATH.is_file():
                try:
                    library = _read_library(PRESETS_BACKUP_PATH)
                    _archive_corrupt(PRESETS_PATH)
                    _write_payload(PRESETS_PATH, library.to_payload())
                    save_legacy_download_preferences(library.default_preset.to_preferences())
                    return library
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            _archive_corrupt(PRESETS_PATH)

    if PRESETS_BACKUP_PATH.is_file():
        try:
            library = _read_library(PRESETS_BACKUP_PATH)
            _write_payload(PRESETS_PATH, library.to_payload())
            save_legacy_download_preferences(library.default_preset.to_preferences())
            return library
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            _archive_corrupt(PRESETS_BACKUP_PATH)

    library = _create_initial_library()
    save_preset_library(library, rotate_backup=False)
    _mirror_primary_to_backup()
    return library


def save_preset_library(
    library: PresetLibrary,
    *,
    rotate_backup: bool = True,
) -> None:
    library._validate()
    PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if rotate_backup and PRESETS_PATH.is_file():
        # 정상 파일일 때만 기존본을 백업으로 승격한다. 깨진 주 파일로 정상 백업을
        # 덮어쓰는 일을 막는다.
        try:
            _read_library(PRESETS_PATH)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        else:
            shutil.copy2(PRESETS_PATH, PRESETS_BACKUP_PATH)

    _write_payload(PRESETS_PATH, library.to_payload())
    # 새로 저장된 주 파일을 다시 읽어 실제 교체 성공까지 확인한다.
    verified = _read_library(PRESETS_PATH)
    if verified.to_payload() != library.to_payload():
        raise OSError("다운로드 프리셋 저장 검증에 실패했습니다.")

    save_legacy_download_preferences(library.default_preset.to_preferences())


def reset_preset_library() -> PresetLibrary:
    library = _create_initial_library()
    save_preset_library(library, rotate_backup=False)
    _mirror_primary_to_backup()
    return library


def export_preset_payload() -> dict[str, Any]:
    return load_preset_library().to_payload()


def import_preset_payload(payload: dict[str, Any]) -> PresetLibrary:
    library = PresetLibrary.from_payload(payload)
    save_preset_library(library, rotate_backup=False)
    _mirror_primary_to_backup()
    return library
