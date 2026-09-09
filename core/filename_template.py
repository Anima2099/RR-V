from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping


DEFAULT_FILENAME_TEMPLATE = "{제목}"
MAX_FILENAME_TEMPLATE_LENGTH = 180
FILENAME_TEMPLATE_TOKEN_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("{제목}", "제목"),
    ("{채널명}", "채널명"),
    ("{영상ID}", "영상 ID"),
    ("{사이트}", "사이트"),
    ("{해상도}", "해상도"),
    ("{업로드날짜}", "업로드 날짜 8자리"),
    ("{업로드날짜6}", "업로드 날짜 6자리"),
    ("{재생시간}", "재생시간"),
    ("{프리셋}", "프리셋"),
    ("{코덱}", "코덱"),
)
FILENAME_TEMPLATE_TOKENS = tuple(
    token for token, _label in FILENAME_TEMPLATE_TOKEN_DEFINITIONS
)
_FILENAME_TEMPLATE_TOKEN_NAMES = {
    token[1:-1] for token in FILENAME_TEMPLATE_TOKENS
}
_TOKEN_PATTERN = re.compile(r"\{([^{}]+)\}")
_DURATION_HOURS_PATTERN = re.compile(r"(\d+)\s*시간")
_DURATION_MINUTES_PATTERN = re.compile(r"(\d+)\s*분")
_DURATION_SECONDS_PATTERN = re.compile(r"(\d+)\s*초")
_NO_AUTO_SPACE_AFTER = frozenset("-_./\\:;|,[({")
_NO_AUTO_SPACE_BEFORE = frozenset("-_./\\:;|,[]()}")


def normalize_filename_template(value: object) -> str:
    template = unicodedata.normalize("NFC", str(value or "")).strip()
    return template or DEFAULT_FILENAME_TEMPLATE


def validate_filename_template(value: object) -> tuple[bool, str]:
    template = normalize_filename_template(value)
    if len(template) > MAX_FILENAME_TEMPLATE_LENGTH:
        return (
            False,
            f"템플릿은 {MAX_FILENAME_TEMPLATE_LENGTH}자 이내로 입력해 주세요.",
        )

    unknown_tokens = sorted(
        {
            match.group(1)
            for match in _TOKEN_PATTERN.finditer(template)
            if match.group(1) not in _FILENAME_TEMPLATE_TOKEN_NAMES
        }
    )
    if unknown_tokens:
        joined = ", ".join(f"{{{name}}}" for name in unknown_tokens)
        return False, f"지원하지 않는 토큰입니다: {joined}"

    without_tokens = _TOKEN_PATTERN.sub("", template)
    if "{" in without_tokens or "}" in without_tokens:
        return False, "중괄호가 올바르게 닫혔는지 확인해 주세요."

    return True, ""


def render_filename_template(
    template: object,
    values: Mapping[str, object],
) -> str:
    normalized = normalize_filename_template(template)
    valid, message = validate_filename_template(normalized)
    if not valid:
        raise ValueError(message)

    def replace_token(match: re.Match[str]) -> str:
        name = match.group(1)
        value = unicodedata.normalize(
            "NFC",
            str(values.get(name, "") or ""),
        ).strip()
        return value

    rendered = _TOKEN_PATTERN.sub(replace_token, normalized)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    return rendered or "video"


def insert_filename_template_token(
    text: str,
    cursor_position: int,
    token: str,
    *,
    auto_spacing: bool,
) -> tuple[str, int]:
    """토큰 버튼 삽입용 보조 함수. 직접 입력한 템플릿은 절대 재작성하지 않는다."""
    source = str(text or "")
    position = max(0, min(len(source), int(cursor_position)))
    left = source[:position]
    right = source[position:]

    prefix = ""
    suffix = ""
    if auto_spacing:
        if left:
            previous = left[-1]
            if not previous.isspace() and previous not in _NO_AUTO_SPACE_AFTER:
                prefix = " "
        if right:
            following = right[0]
            if not following.isspace() and following not in _NO_AUTO_SPACE_BEFORE:
                suffix = " "

    insertion = f"{prefix}{token}{suffix}"
    return left + insertion + right, position + len(insertion)


def site_label(extractor: object) -> str:
    raw = str(extractor or "").strip()
    lowered = raw.lower()
    if "youtube" in lowered:
        return "YouTube"
    if "instagram" in lowered:
        return "Instagram"
    if "tiktok" in lowered:
        return "TikTok"
    if "weverse" in lowered:
        return "Weverse"
    if "naver" in lowered:
        return "Naver"
    return raw.split(":", 1)[0].strip() or "Unknown"


def normalize_upload_date(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 8:
        return digits
    return ""


def resolution_filename_label(
    selected_resolution: object,
    *,
    probed_height: int | None = None,
    audio_only: bool = False,
) -> str:
    if audio_only:
        return "오디오"
    if probed_height is not None and probed_height > 0:
        return f"{int(probed_height)}p"

    raw = str(selected_resolution or "").strip()
    mapping = {
        "8K (4320p)": "4320p",
        "4K (2160p)": "2160p",
        "1440p": "1440p",
        "1080p": "1080p",
        "720p": "720p",
        "480p": "480p",
        "최고 화질": "최고화질",
    }
    return mapping.get(raw, raw.replace(" ", "") or "해상도미상")


def codec_filename_label(
    selected_codec: object,
    *,
    probed_codec: object = "",
    audio_only: bool = False,
    audio_format: object = "",
) -> str:
    if audio_only:
        return str(audio_format or "오디오").strip() or "오디오"

    raw = str(probed_codec or selected_codec or "").strip()
    lowered = raw.lower()
    if lowered.startswith("avc1") or lowered in {"h264", "h.264"}:
        return "H264"
    if (
        lowered.startswith("hev1")
        or lowered.startswith("hvc1")
        or lowered in {"hevc", "h265", "h.265"}
    ):
        return "H265"
    if lowered.startswith("av01") or lowered == "av1":
        return "AV1"
    if lowered.startswith("vp09") or lowered.startswith("vp9"):
        return "VP9"
    return raw.replace(".", "") or "코덱미상"


def duration_filename_label(
    duration_text: object,
    *,
    duration_seconds: float | int | None = None,
) -> str:
    total_seconds: int | None = None
    if duration_seconds is not None:
        try:
            total_seconds = max(0, int(float(duration_seconds)))
        except (TypeError, ValueError, OverflowError):
            total_seconds = None

    if total_seconds is None:
        text = str(duration_text or "")
        hours_match = _DURATION_HOURS_PATTERN.search(text)
        minutes_match = _DURATION_MINUTES_PATTERN.search(text)
        seconds_match = _DURATION_SECONDS_PATTERN.search(text)
        if hours_match or minutes_match or seconds_match:
            hours = int(hours_match.group(1)) if hours_match else 0
            minutes = int(minutes_match.group(1)) if minutes_match else 0
            seconds = int(seconds_match.group(1)) if seconds_match else 0
            total_seconds = max(0, hours * 3600 + minutes * 60 + seconds)

    if total_seconds is None:
        return "시간미상"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def filename_template_values(
    *,
    title: object,
    uploader: object,
    video_id: object,
    extractor: object,
    resolution: object = "",
    upload_date: object = "",
    duration_text: object = "",
    duration_seconds: float | int | None = None,
    preset: object = "",
    codec: object = "",
    probed_height: int | None = None,
    probed_codec: object = "",
    audio_only: bool = False,
    audio_format: object = "",
) -> dict[str, str]:
    date8 = normalize_upload_date(upload_date)
    return {
        "제목": unicodedata.normalize("NFC", str(title or "video")).strip() or "video",
        "채널명": unicodedata.normalize(
            "NFC",
            str(uploader or "알 수 없는 채널"),
        ).strip()
        or "알 수 없는 채널",
        "영상ID": str(video_id or "").strip() or "unknown",
        "사이트": site_label(extractor),
        "해상도": resolution_filename_label(
            resolution,
            probed_height=probed_height,
            audio_only=audio_only,
        ),
        "업로드날짜": date8 or "날짜미상",
        "업로드날짜6": date8[2:] if date8 else "날짜미상",
        "재생시간": duration_filename_label(
            duration_text,
            duration_seconds=duration_seconds,
        ),
        "프리셋": unicodedata.normalize(
            "NFC",
            str(preset or "기본 다운로드"),
        ).strip()
        or "기본 다운로드",
        "코덱": codec_filename_label(
            codec,
            probed_codec=probed_codec,
            audio_only=audio_only,
            audio_format=audio_format,
        ),
    }
