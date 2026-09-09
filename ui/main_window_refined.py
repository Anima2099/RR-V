from __future__ import annotations

import ui.main_window as _main_window
from ui.pages.download_page_refined import DownloadPage as RefinedDownloadPage


class MainWindow(_main_window.MainWindow):
    """Build the normal shell with the 1.4 refined download page."""

    def __init__(self) -> None:
        original_download_page = _main_window.DownloadPage
        _main_window.DownloadPage = RefinedDownloadPage
        try:
            super().__init__()
        finally:
            _main_window.DownloadPage = original_download_page


__all__ = ["MainWindow"]
