from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QSettings

from app.settings_store import get_settings


LEGACY_PRESET_NAMES: tuple[str, ...] = (
    "기본 다운로드",
    "최고 품질",
    "호환성 우선",
    "작은 파일",
    "오디오만",
)

# 1.0.x 코드와 외부 참조를 위한 호환 별칭이다. 1.1.0의 실제 프리셋 목록은
# app.preset_store에서 동적으로 관리한다.
PRESET_NAMES = LEGACY_PRESET_NAMES

RESOLUTION_CHOICES: tuple[str, ...] = (
    "최고 화질",
    "8K (4320p)",
    "4K (2160p)",
    "1440p",
    "1080p",
    "720p",
    "480p",
)

CONTAINER_CHOICES: tuple[str, ...] = ("MP4", "MKV", "WebM")
CODEC_CHOICES: tuple[str, ...] = ("H.264", "VP9", "AV1")
AUDIO_FORMAT_CHOICES: tuple[str, ...] = ("M4A", "MP3", "Opus", "FLAC")
AUDIO_QUALITY_CHOICES: tuple[str, ...] = ("최고", "320k", "256k", "192k")

SUBTITLE_LANGUAGE_LABELS: dict[str, str] = {
    "ko": "한국어",
    "en": "영어",
    "ja": "일본어",
}


@dataclass(slots=True)
class DownloadPreferences:
    """다운로드 한 건에 적용할 완전한 옵션 묶음.

    1.1.0부터 프리셋 정의는 app.preset_store.DownloadPreset이 소유하고,
    이 객체는 선택된 프리셋을 실제 다운로드/미리보기 코드에 전달하는 실행값으로
    사용한다.
    """

    preset_id: str = ""
    preset: str = "기본 다운로드"
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

    def normalized(self) -> "DownloadPreferences":
        preferred: list[str] = []
        seen: set[str] = set()
        for item in self.preferred_subtitles:
            value = str(item).strip().lower()
            if value and value not in seen:
                seen.add(value)
                preferred.append(value)

        return replace(
            self,
            preset_id=str(self.preset_id).strip(),
            preset=str(self.preset).strip() or "기본 다운로드",
            resolution=(
                self.resolution
                if self.resolution in RESOLUTION_CHOICES
                else "최고 화질"
            ),
            container=(
                self.container if self.container in CONTAINER_CHOICES else "MP4"
            ),
            codec=self.codec if self.codec in CODEC_CHOICES else "H.264",
            preferred_subtitles=tuple(preferred),
            audio_format=(
                self.audio_format
                if self.audio_format in AUDIO_FORMAT_CHOICES
                else "M4A"
            ),
            audio_quality=(
                self.audio_quality
                if self.audio_quality in AUDIO_QUALITY_CHOICES
                else "최고"
            ),
        )

    def with_legacy_preset(self, preset: str) -> "DownloadPreferences":
        """1.0.x의 하드코딩 프리셋 동작을 재현한다.

        1.1.0 첫 실행 시 기존 사용자 설정을 사용자 프리셋 5개로 이관할 때만
        사용한다. 자막/썸네일 같은 공통 옵션은 기존 사용자 값 그대로 유지한다.
        """

        preset = preset if preset in LEGACY_PRESET_NAMES else "기본 다운로드"
        updated = replace(self, preset_id="", preset=preset)

        if preset == "최고 품질":
            return replace(
                updated,
                resolution="최고 화질",
                container="MKV",
                codec="AV1",
                preserve_metadata=True,
                audio_only=False,
            )
        if preset == "호환성 우선":
            return replace(
                updated,
                resolution="1080p",
                container="MP4",
                codec="H.264",
                preserve_metadata=True,
                audio_only=False,
            )
        if preset == "작은 파일":
            return replace(
                updated,
                resolution="720p",
                container="MP4",
                codec="H.264",
                preserve_metadata=True,
                audio_only=False,
            )
        if preset == "오디오만":
            return replace(
                updated,
                audio_only=True,
                audio_format="M4A",
                audio_quality="최고",
                preserve_metadata=True,
            )

        return replace(
            updated,
            resolution="최고 화질",
            container="MP4",
            codec="H.264",
            preserve_metadata=True,
            audio_only=False,
        )

    # 1.0.x 내부 호출과의 호환을 위해 남긴다. 새 코드는 PresetStore에서 실제
    # 프리셋을 읽어야 한다.
    def with_preset(self, preset: str) -> "DownloadPreferences":
        return self.with_legacy_preset(preset)


def _settings() -> QSettings:
    return get_settings()


def _read_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_string_list(
    settings: QSettings,
    key: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = settings.value(key, list(default))
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple)):
        values = [str(item).strip() for item in value]
    else:
        values = list(default)

    ordered: list[str] = []
    seen: set[str] = set()
    for item in values:
        lowered = item.lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            ordered.append(lowered)
    return tuple(ordered)


def load_legacy_download_preferences() -> DownloadPreferences:
    """settings.ini에 남아 있는 1.0.x 기본 다운로드 설정을 읽는다."""

    settings = _settings()
    preferences = DownloadPreferences(
        preset=str(settings.value("downloads/default_preset", "기본 다운로드")),
        resolution=str(settings.value("downloads/default_resolution", "최고 화질")),
        container=str(settings.value("downloads/default_container", "MP4")),
        codec=str(settings.value("downloads/default_codec", "H.264")),
        receive_subtitles=_read_bool(settings, "downloads/receive_subtitles", True),
        preferred_subtitles=_read_string_list(
            settings,
            "downloads/preferred_subtitles",
            ("ko",),
        ),
        allow_automatic_subtitles=_read_bool(
            settings,
            "downloads/allow_automatic_subtitles",
            True,
        ),
        embed_subtitles=_read_bool(settings, "downloads/embed_subtitles", True),
        embed_thumbnail=_read_bool(settings, "downloads/embed_thumbnail", False),
        save_thumbnail=_read_bool(settings, "downloads/save_thumbnail", False),
        preserve_metadata=_read_bool(settings, "downloads/preserve_metadata", True),
        audio_only=_read_bool(settings, "downloads/audio_only", False),
        audio_format=str(settings.value("downloads/audio_format", "M4A")),
        audio_quality=str(settings.value("downloads/audio_quality", "최고")),
    ).normalized()

    return preferences


def save_legacy_download_preferences(preferences: DownloadPreferences) -> None:
    """현재 기본 프리셋을 settings.ini에도 복구용 거울값으로 저장한다."""

    preferences = preferences.normalized()
    settings = _settings()
    settings.setValue("downloads/default_preset", preferences.preset)
    settings.setValue("downloads/default_resolution", preferences.resolution)
    settings.setValue("downloads/default_container", preferences.container)
    settings.setValue("downloads/default_codec", preferences.codec)
    settings.setValue("downloads/receive_subtitles", preferences.receive_subtitles)
    settings.setValue(
        "downloads/preferred_subtitles",
        list(preferences.preferred_subtitles),
    )
    settings.setValue(
        "downloads/allow_automatic_subtitles",
        preferences.allow_automatic_subtitles,
    )
    settings.setValue("downloads/embed_subtitles", preferences.embed_subtitles)
    settings.setValue("downloads/embed_thumbnail", preferences.embed_thumbnail)
    settings.setValue("downloads/save_thumbnail", preferences.save_thumbnail)
    settings.setValue("downloads/preserve_metadata", preferences.preserve_metadata)
    settings.setValue("downloads/audio_only", preferences.audio_only)
    settings.setValue("downloads/audio_format", preferences.audio_format)
    settings.setValue("downloads/audio_quality", preferences.audio_quality)
    settings.sync()


def load_download_preferences() -> DownloadPreferences:
    """현재 기본 사용자 프리셋의 실행값을 반환한다."""

    from app.preset_store import load_preset_library

    return load_preset_library().default_preset.to_preferences()


def save_download_preferences(preferences: DownloadPreferences) -> None:
    """호환 API: 현재 기본 프리셋의 값을 갱신한다."""

    from app.preset_store import load_preset_library, save_preset_library

    library = load_preset_library()
    library.replace_preset(
        library.default_preset_id,
        library.default_preset.with_preferences(preferences),
    )
    save_preset_library(library)
