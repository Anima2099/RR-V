from __future__ import annotations

import colorsys
import re


PRIMARY_TEXT = "#E2E7E3"
SECONDARY_TEXT = "#B6C0BA"
MUTED_TEXT = "#98A49D"
DISABLED_TEXT = "#78847D"
ON_ACCENT = "#F7FAF8"
LINK_TEXT = "#78A7BA"
ACCENT = "#55798A"
ACCENT_BORDER = "#6F94A5"
SUCCESS_TEXT = "#8DB596"
ERROR_TEXT = "#D8877E"
WARNING_TEXT = "#D0A96D"

BG_MAIN = "#202723"
BG_SIDEBAR = "#27302B"
BG_INPUT = "#252D29"
BG_CARD = "#2C3530"
BG_SUBTLE = "#323B36"
BG_RAISED = "#353F3A"
BG_HOVER = "#39463F"
BG_SELECTED = "#3B4A42"
BG_DISABLED = "#303833"
BORDER = "#46524C"


_CORE_BACKGROUNDS = {
    "#E3E1D9": BG_MAIN,
    "#D3DACF": BG_SIDEBAR,
    "#FCF9F1": BG_INPUT,
    "#F7F4EB": BG_CARD,
    "#ECEAE3": BG_SUBTLE,
    "#EEECE5": "#303934",
    "#ECEDE7": "#303934",
    "#E5E7E1": "#343D38",
    "#E7E7E1": "#343D38",
    "#ECEFE8": "#2D3732",
    "#E6EBE4": "#344139",
    "#F6F3EB": "#303A35",
    "#F8F5ED": "#303A35",
    "#F1EFE8": "#29322E",
    "#F1EFE7": "#29322E",
    "#F0EEE7": "#29322E",
    "#E5E4DE": "#39423D",
    "#E2E1DC": BG_DISABLED,
    "#E8E7E2": BG_DISABLED,
    "#D4D8CF": BG_DISABLED,
    "#D9E3DD": BG_SELECTED,
    "#D7DFD7": "#354039",
    "#D6E1DA": "#35443A",
    "#D9E0D9": BG_HOVER,
    "#DCE2DC": BG_HOVER,
    "#E8ECE6": "#36413B",
    "#ECEFE9": "#343E39",
    "#E2E8E1": "#304038",
    "#E2E5DF": "#343D38",
    "#E9ECE4": "#313A35",
    "#DCE3DB": "#3A4740",
    "#CFD8CF": "#344139",
    "#FBF8EF": "#303A35",
}

_SEMANTIC_BACKGROUNDS = {
    "#D9E5E9": "#293941",
    "#D7E3E8": "#293941",
    "#DDE7E8": "#2A3A40",
    "#DDEADB": "#293B30",
    "#DDE8DA": "#293B30",
    "#EBDDD9": "#3A2928",
    "#E7D8D4": "#3A2928",
    "#E2CFCA": "#432F2D",
    "#F0DFDC": "#3A2928",
    "#F0DDDC": "#3A2928",
    "#ECDADA": "#3A2928",
    "#E9DAD7": "#3A2928",
    "#E2C9C5": "#432F2D",
    "#DFC4C0": "#432F2D",
    "#D9BDB8": "#432F2D",
    "#D8BBB7": "#432F2D",
    "#EEE5D8": "#3A3226",
    "#E7DFD3": "#3A3226",
    "#E7D9BE": "#403623",
}

_SUCCESS_COLORS = {
    "#557955", "#608158", "#56805A", "#527451", "#789871", "#789685",
    "#8FA99B", "#8EAB99", "#9AB6A4", "#93A37E", "#8FA078", "#A3B18A",
    "#B1BE9D",
}
_ERROR_COLORS = {
    "#8D554F", "#985E55", "#A55353", "#9A5656", "#975757", "#8C5050",
    "#8A4F4D", "#7E403E", "#B97979", "#A15F4C",
}
_WARNING_COLORS = {
    "#B99558", "#B49A72", "#9A6A50", "#8A765A", "#8A6A4D", "#846D4C",
    "#7A6E59", "#6A5532",
}
_BLUE_COLORS = {
    "#608598", "#55798A", "#4B6E7D", "#496E80", "#4E7486", "#456C7D",
    "#567486",
}


def _rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]


def _hls(color: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*_rgb(color))


def _hex_from_hls(hue: float, lightness: float, saturation: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    values = tuple(
        max(0, min(255, round(channel * 255)))
        for channel in (red, green, blue)
    )
    return "#%02X%02X%02X" % values


def _semantic_family(color: str) -> str | None:
    value = color.upper()
    if value in _SUCCESS_COLORS:
        return "success"
    if value in _ERROR_COLORS:
        return "error"
    if value in _WARNING_COLORS:
        return "warning"
    if value in _BLUE_COLORS:
        return "blue"

    hue, _lightness, saturation = _hls(value)
    degrees = hue * 360
    if saturation >= 0.18:
        if degrees < 25 or degrees >= 340:
            return "error"
        if 25 <= degrees < 65:
            return "warning"
        if 70 <= degrees < 175:
            return "success"
        if 175 <= degrees < 250:
            return "blue"
    return None


def _map_text(color: str) -> str:
    value = color.upper()
    if value in {"#FFFDF8", "#FBF8EF"}:
        return ON_ACCENT

    family = _semantic_family(value)
    if family == "success":
        return SUCCESS_TEXT
    if family == "error":
        return ERROR_TEXT
    if family == "warning":
        return WARNING_TEXT
    if family == "blue":
        return LINK_TEXT

    _hue, lightness, _saturation = _hls(value)
    if lightness < 0.33:
        return PRIMARY_TEXT
    if lightness < 0.48:
        return SECONDARY_TEXT
    if lightness < 0.68:
        return MUTED_TEXT
    return DISABLED_TEXT


def _map_background(color: str) -> str:
    value = color.upper()
    if value in _SEMANTIC_BACKGROUNDS:
        return _SEMANTIC_BACKGROUNDS[value]
    if value in _CORE_BACKGROUNDS:
        return _CORE_BACKGROUNDS[value]
    if value == "#608598":
        return ACCENT
    if value == "#55798A":
        return "#4E7181"
    if value == "#4B6E7D":
        return "#4B6E7D"
    if value == "#A3B18A":
        return "#465240"
    if value == "#B1BE9D":
        return "#52614B"
    if value == "#93A37E":
        return "#3C4938"

    family = _semantic_family(value)
    hue, lightness, saturation = _hls(value)
    if family == "success" and lightness > 0.55:
        return "#293B30"
    if family == "error" and lightness > 0.55:
        return "#3A2928"
    if family == "warning" and lightness > 0.55:
        return "#3A3226"
    if family == "blue" and lightness > 0.55:
        return "#293941"
    if lightness >= 0.90:
        return BG_CARD
    if lightness >= 0.82:
        return BG_SUBTLE
    if lightness >= 0.72:
        return BG_RAISED
    if lightness >= 0.60:
        return BG_HOVER
    return _hex_from_hls(
        hue,
        max(0.22, min(0.36, lightness * 0.72)),
        min(0.30, max(0.08, saturation * 0.75)),
    )


def _map_border(color: str) -> str:
    value = color.upper()
    family = _semantic_family(value)
    if value == "#608598" or family == "blue":
        return ACCENT_BORDER
    if family == "success":
        return "#5D7564"
    if family == "error":
        return "#6F4945"
    if family == "warning":
        return "#705E3F"

    _hue, lightness, _saturation = _hls(value)
    if lightness > 0.72:
        return BORDER
    if lightness > 0.55:
        return "#536159"
    return "#5B6A62"


def _map_color(property_name: str, color: str) -> str:
    prop = property_name.strip().lower()
    if prop == "color":
        return _map_text(color)
    if prop == "selection-color":
        return ON_ACCENT
    if prop == "selection-background-color":
        return ACCENT
    if prop in {"background-color", "alternate-background-color"}:
        return _map_background(color)
    if prop.startswith("border"):
        return _map_border(color)
    return _map_text(color)


def build_dark_stylesheet(light_stylesheet: str) -> str:
    """검증된 Light QSS의 selector 구조를 유지한 채 Warm Sage Dark 색만 치환한다."""
    output: list[str] = []
    for line in light_stylesheet.splitlines():
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("/*"):
            property_name = stripped.split(":", 1)[0]
            line = re.sub(
                r"#[0-9A-Fa-f]{6}",
                lambda match: _map_color(property_name, match.group(0)),
                line,
            )
        output.append(line)

    dark = "\n".join(output) + "\n"

    # 목업 확인 후 가독성과 상태 구분을 위해 일부 핵심 색을 의도적으로 보정한다.
    replacements = {
        "QLabel#mutedText {\n    font-size: 12pt;\n    color: #B6C0BA;":
            "QLabel#mutedText {\n    font-size: 12pt;\n    color: #98A49D;",
        "QLabel#emptyDescription {\n    font-size: 12pt;\n    color: #B6C0BA;":
            "QLabel#emptyDescription {\n    font-size: 12pt;\n    color: #98A49D;",
        "QPushButton#primaryButton:hover {\n    background-color: #4E7181;":
            "QPushButton#primaryButton:hover {\n    background-color: #608598;",
        "QPushButton#primaryButton:disabled {\n    background-color: #39463F;\n    color: #78847D;":
            "QPushButton#primaryButton:disabled {\n    background-color: #39463F;\n    color: #8C9891;",
        "QPushButton#toolLinkButton:hover {\n    color: #78A7BA;":
            "QPushButton#toolLinkButton:hover {\n    color: #8AB6C8;",
        "QProgressBar#taskProgress[taskStatus=\"postprocessing\"]::chunk {\n    background-color: #776340;":
            "QProgressBar#taskProgress[taskStatus=\"postprocessing\"]::chunk {\n    background-color: #A8844E;",
        "QProgressBar#taskProgress[taskStatus=\"completed\"]::chunk {\n    background-color: #556751;":
            "QProgressBar#taskProgress[taskStatus=\"completed\"]::chunk {\n    background-color: #6E9477;",
        "QProgressBar#taskProgress[taskStatus=\"failed\"]::chunk {\n    background-color: #3A2928;":
            "QProgressBar#taskProgress[taskStatus=\"failed\"]::chunk {\n    background-color: #B9655D;",
        "QProgressBar#taskProgress[taskStatus=\"stopped\"]::chunk {\n    background-color: #3A3226;":
            "QProgressBar#taskProgress[taskStatus=\"stopped\"]::chunk {\n    background-color: #A8844E;",
        "QProgressBar#taskProgress[taskStatus=\"analyzing\"]::chunk {\n    background-color: #293B30;":
            "QProgressBar#taskProgress[taskStatus=\"analyzing\"]::chunk {\n    background-color: #6F94A5;",
    }
    for before, after in replacements.items():
        dark = dark.replace(before, after)
    return dark
