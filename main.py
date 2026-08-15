import os
import sys

# RR-V가 LocalAppData에 복사한 WPC/nodriver 런타임에 __pycache__를 만들지 않는다.
sys.dont_write_bytecode = True

# Chrome/Edge Native Messaging은 RR-V.exe 자체를 짧은 브리지 프로세스로
# 실행한다. 이 모드는 GUI/Qt 초기화 전에 stdio 메시지 하나만 처리하고 종료한다.
from services.native_messaging_host import (
    is_native_messaging_invocation,
    run_native_messaging_host,
)

if is_native_messaging_invocation(sys.argv[1:]):
    sys.exit(run_native_messaging_host())

from PySide6.QtCore import QTimer

from app.application import create_application
from app.general_preferences import load_general_preferences
from services.external_url_service import ExternalUrlService, extract_external_urls
from services.windows_startup_service import (
    WindowsStartupError,
    sync_windows_startup_registration,
)
from services.browser_integration_service import sync_browser_integration_registration
from ui.dialogs.warm_dialogs import show_warm_message
from ui.main_window import MainWindow


def _prepare_windowed_stdio() -> None:
    """PyInstaller windowed 실행에서 print/log 출력이 시작을 막지 않게 한다."""

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> int:
    _prepare_windowed_stdio()
    app = create_application(sys.argv)
    command_arguments = sys.argv[1:]
    startup_hidden_requested = "--startup-hidden" in command_arguments
    browser_extension_requested = "--browser-extension" in command_arguments
    external_source = "browser" if browser_extension_requested else "external"
    external_urls = extract_external_urls(command_arguments)

    external_service = ExternalUrlService(app)
    # 명시적 QApplication 종료 시 로컬 서버/lock/endpoint를 이벤트 루프가
    # 반환되기 전에 먼저 닫는다. finally의 close()는 이중 안전망이다.
    app.aboutToQuit.connect(external_service.close)
    if not external_service.try_become_primary():
        # URL과 함께 실행된 두 번째 프로세스는 기존 창을 방해하지 않고 URL만
        # 전달한다. 사용자가 RR-V 자체를 다시 실행한 경우에는 기존 창을 연다.
        activate_existing = not bool(external_urls) and not startup_hidden_requested
        if external_service.forward_to_primary(
            external_urls,
            activate=activate_existing,
            source=external_source,
        ):
            return 0

        # 비정상 종료로 잠금만 남은 경우에 한해 한 번 복구한다.
        if not external_service.try_recover_stale_primary():
            if external_service.forward_to_primary(
                external_urls,
                activate=activate_existing,
                source=external_source,
            ):
                return 0
            show_warm_message(
                None,
                "RR-V 실행 확인",
                "이미 실행 중인 RR-V와 연결하지 못했습니다.\n"
                "잠시 후 다시 실행해 주세요.",
            )
            return 1

    general_preferences = load_general_preferences()
    try:
        sync_browser_integration_registration()
    except Exception as error:
        print(f"RR-V browser integration registration sync failed: {error}")

    if general_preferences.start_with_windows and not startup_hidden_requested:
        try:
            sync_windows_startup_registration(
                True,
                start_hidden=general_preferences.minimize_to_tray_on_close,
            )
        except WindowsStartupError as error:
            print(f"RR-V Windows startup registration sync failed: {error}")

    window = MainWindow()
    external_service.request_received.connect(window.handle_external_request)

    started_hidden = False
    if startup_hidden_requested:
        started_hidden = window.start_hidden_to_tray()
    if not started_hidden:
        window.show()

    if external_urls:
        # DownloadPage의 시작 시 복원 작업과 UI 구성이 끝난 뒤 외부 요청을 넣는다.
        QTimer.singleShot(
            900,
            lambda urls=tuple(external_urls), source=external_source: window.handle_external_request(
                list(urls),
                False,
                source,
                reveal_download_page=True,
            ),
        )

    try:
        return app.exec()
    finally:
        external_service.close()


if __name__ == "__main__":
    sys.exit(main())
