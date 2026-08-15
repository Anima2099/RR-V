from collections.abc import Sequence

from time import perf_counter

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QIcon
from PySide6.QtWidgets import QApplication

from app.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_FONT_SIZE,
    ORGANIZATION_NAME,
)
from app.paths import (
    CLOSE_ICON_PATH,
    STOP_ICON_PATH,
    COPY_ICON_PATH,
    DRAG_ICON_PATH,
    MORE_ICON_PATH,
    RETRY_ICON_PATH,
    SPIN_DOWN_ICON_PATH,
    SPIN_UP_ICON_PATH,
    APP_ICON_PATH,
    WARM_SAGE_THEME_PATH,
)
from app.download_log import download_log_path
from app.settings_backup import ensure_daily_auto_backup
from app.settings_store import initialize_settings_store
from app.converter_log import converter_log_path
from app.snapshot_log import snapshot_log_path
from app.subtitle_log import subtitle_log_path
from app.performance_log import (
    initialize_performance_log,
    performance_log_path,
    write_performance,
)


def choose_application_font() -> QFont:
    installed_fonts = set(QFontDatabase.families())

    font_candidates = [
        "Malgun Gothic",
        "맑은 고딕",
        "Noto Sans KR",
    ]

    selected_family = next(
        (
            family
            for family in font_candidates
            if family in installed_fonts
        ),
        QApplication.font().family(),
    )

    font = QFont(selected_family)
    font.setPointSize(DEFAULT_FONT_SIZE)
    font.setWeight(QFont.Weight.Normal)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(
        QFont.HintingPreference.PreferFullHinting
    )

    return font


def load_theme() -> str:
    try:
        theme = WARM_SAGE_THEME_PATH.read_text(encoding="utf-8")
    except OSError as error:
        print(f"RR-V theme load failed: {error}")
        return ""

    replacements = {
        "__SPIN_UP_ICON__": f'"{SPIN_UP_ICON_PATH.as_posix()}"',
        "__SPIN_DOWN_ICON__": f'"{SPIN_DOWN_ICON_PATH.as_posix()}"',
    }
    for marker, value in replacements.items():
        theme = theme.replace(marker, value)
    return theme



def preload_task_icons() -> None:
    started = perf_counter()
    paths = (
        DRAG_ICON_PATH,
        RETRY_ICON_PATH,
        COPY_ICON_PATH,
        MORE_ICON_PATH,
        CLOSE_ICON_PATH,
        STOP_ICON_PATH,
        SPIN_UP_ICON_PATH,
        SPIN_DOWN_ICON_PATH,
    )
    for path in paths:
        # SVG 플러그인과 아이콘 픽스맵 캐시를 프로그램 시작 때 미리 준비한다.
        QIcon(str(path)).pixmap(20, 20)
    write_performance(
        "startup.preload_task_icons",
        (perf_counter() - started) * 1000.0,
        count=len(paths),
    )

def create_application(arguments: Sequence[str]) -> QApplication:
    initialize_performance_log()
    app = QApplication(list(arguments))

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    app.setStyle("Fusion")

    try:
        initialize_settings_store()
    except OSError as error:
        print(f"RR-V settings store migration failed: {error}")

    try:
        ensure_daily_auto_backup()
    except OSError as error:
        print(f"RR-V settings auto backup failed: {error}")

    application_font = choose_application_font()
    app.setFont(application_font)
    app.setStyleSheet(load_theme())
    preload_task_icons()

    resolved_font = QFontInfo(app.font())
    print(
        f"RR-V font: {resolved_font.family()} "
        f"{resolved_font.pointSize()}pt"
    )
    print(f"RR-V performance log: {performance_log_path()}", flush=True)
    print(f"RR-V download log: {download_log_path()}", flush=True)
    print(f"RR-V converter log: {converter_log_path()}", flush=True)
    print(f"RR-V snapshot log: {snapshot_log_path()}", flush=True)
    print(f"RR-V subtitle log: {subtitle_log_path()}", flush=True)

    return app
