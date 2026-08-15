# RR-V

**RR-V** is a Windows VOD downloader and local media-tools application built with Python and PySide6.

Current source version: **1.1.2**

> This repository currently has no open-source license selected. Do not assume permission to redistribute the RR-V source or assets.

## What RR-V does

- VOD information lookup and download workflow based on yt-dlp / FFmpeg
- Single and batch URL handling, TXT import/export, quick add, and queue management
- Failed-task filtering and retry workflows
- Thumbnail-only and subtitle-only recovery
- Custom download presets and per-task save-path handling
- YouTube, Instagram, and TikTok RR-V-managed login support
- Chrome / Edge browser connector with Native Messaging and local fast-path delivery
- Windows system-tray residence and startup integration
- Media tools for conversion, thumbnails, snapshots, and subtitles

TikTok login support is implemented, but actual TikTok extraction can still depend on the current behavior of yt-dlp and TikTok.

## Repository layout

```text
app/                  application settings, paths, stores, and shared app logic
controllers/          UI/controller coordination
core/                 core data models
services/             download, authentication, browser integration, media services
ui/                   main window, pages, dialogs, and widgets
workers/              background worker objects
resources/            icons, theme, browser connector, tool/runtime metadata
main.py                application entry point
RR-V.spec              PyInstaller release build specification
PREP_WPC_PROVIDER.ps1  prepares the locked YouTube WPC/nodriver runtime
PACKAGING_CHECKLIST.txt release/regression checklist
```

## Development notes

Install the Python dependencies from `requirements.txt` in the RR-V virtual environment.

The repository intentionally does **not** track generated or machine-local items such as:

- `.venv/`
- PyInstaller `build/` and `dist/`
- `resources/wpc-provider/runtime/`
- third-party seed executables under `resources/tools/`
- logs, queue data, settings, cookies, and login credentials
- local release ZIP files

The WPC/nodriver runtime can be rebuilt from the locked versions using:

```powershell
powershell -ExecutionPolicy Bypass -File .\PREP_WPC_PROVIDER.ps1
```

A final RR-V package also requires the tested local copies of `yt-dlp.exe`, `ffmpeg.exe`, `ffprobe.exe`, and `deno.exe` in `resources\tools` before building. See `resources/tools/README.txt` and `PACKAGING_CHECKLIST.txt`.

## Authentication data

RR-V stores user settings and authentication data outside the source tree under the user's Windows AppData directories. Cookie files contain private login credentials and must never be committed or shared.

The `.gitignore` contains additional defensive rules in case such files are accidentally copied into the project folder.

## Browser connector

The Chromium extension source is under:

`resources/browser-extension/rrv-chromium/`

It is used by the RR-V application to send the current page or selected links to the running application, with Native Messaging as the fallback path when RR-V is not already running.

## Release build

After the required tools and WPC runtime are prepared, the release build is created with the checked-in PyInstaller specification:

```powershell
python -m PyInstaller --clean --noconfirm RR-V.spec
```

Expected output:

`dist\RR-V.exe`

Before a release, follow `PACKAGING_CHECKLIST.txt` and review third-party license/source obligations for all bundled binaries and runtimes.

## Project status

RR-V 1.1.2 is the current release baseline. Development should branch from or otherwise preserve this known-good source state before starting the next feature set.
