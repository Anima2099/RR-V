from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping


DEFAULT_FILENAME_TEMPLATE = "{제목}"
MAX_FILENAME_TEMPLATE_LENGTH = 180
FILENAME_TEMPLATE_TOKENS = (
    "{제목}",
    "{채널명}",
    "{영상ID}",
    "{사이트}",
)
_FILENAME_TEMPLATE_TOKEN_NAMES = {
    token[1:-1] for token in FILENAME_TEMPLATE_TOKENS
}
_TOKEN_PATTERN = re.compile(r"\{([^{}]+)\}")


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


def filename_template_values(
    *,
    title: object,
    uploader: object,
    video_id: object,
    extractor: object,
) -> dict[str, str]:
    return {
        "제목": unicodedata.normalize("NFC", str(title or "video")).strip() or "video",
        "채널명": unicodedata.normalize(
            "NFC",
            str(uploader or "알 수 없는 채널"),
        ).strip()
        or "알 수 없는 채널",
        "영상ID": str(video_id or "").strip() or "unknown",
        "사이트": site_label(extractor),
    }
