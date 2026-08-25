# RR-V

**RR-V** is a Windows VOD downloader and local media-tools application built with Python and PySide6.

Current development version: **1.2.0 Community Beta**

> The RR-V core application currently has no open-source redistribution license selected. Source is made available for inspection and development, but do not assume permission to redistribute the RR-V core source or original assets. The separately distributed `auth_helper` component has its own AGPL-3.0-only license notice.

## What RR-V does

- VOD information lookup and download workflow based on yt-dlp / FFmpeg
- Single and batch URL handling, TXT import/export, quick add, and queue management
- Failed-task filtering and retry workflows
- Thumbnail-only and subtitle-only recovery
- Custom download presets and per-task save-path handling
- RR-V-managed YouTube, Instagram, and TikTok authentication
- Chrome / Edge browser connector with Native Messaging and local fast-path delivery
- Windows system-tray residence and startup integration
- Media tools for conversion, thumbnails, snapshots, and subtitles
- Light / dark Warm Sage themes
- Built-in status and update management for required external tools

TikTok authentication support is implemented, but actual TikTok extraction can still depend on the current behavior of yt-dlp and TikTok.

## 1.2.0 distribution model

RR-V 1.2.0 uses a PyInstaller **onedir** layout.

```text
dist/RR-V/
  RR-V.exe
  RR-V-Auth-Helper.exe
  THIRD_PARTY_NOTICES.txt
  SOURCE_OFFER.txt
  licenses/
  _internal/
```

The RR-V Installer does **not** bundle these large external executables:

- `yt-dlp.exe`
- `ffmpeg.exe`
- `ffprobe.exe`
- `deno.exe`

After RR-V is installed, the user can prepare missing required tools from **Settings > Tools & Resources**. RR-V downloads those tools from their official distribution channels and stores them under the user's LocalAppData RR-V tools directory.

The YouTube WPC/browser-authentication runtime is a separate locked runtime and is bundled as Python source plus package metadata because it is required by RR-V authentication and YouTube PO-token support.

## Authentication boundary

RR-V core no longer imports `nodriver` directly.

```text
RR-V core
   |
   | JSON-lines process protocol
   v
RR-V Auth Helper
   |
   v
nodriver / Chromium browser
```

`RR-V-Auth-Helper.exe` is built as a separate process component. Its source is under `auth_helper/` and is also copied into the release `licenses/` directory. See `auth_helper/README.md`, `auth_helper/LICENSE_NOTICE.txt`, `THIRD_PARTY_NOTICES.txt`, and `SOURCE_OFFER.txt`.

## Repository layout

```text
app/                  application settings, paths, stores, and shared app logic
auth_helper/          isolated browser-authentication helper source
controllers/          UI/controller coordination
core/                 core data models
services/             download, authentication, browser integration, media services
ui/                   main window, pages, dialogs, and widgets
workers/              background worker objects
resources/            icons, theme, browser connector, WPC runtime metadata
main.py                application entry point
RR-V.spec              PyInstaller onedir build specification
RR-V-Auth-Helper.spec  separate Auth Helper build specification
BUILD_RELEASE.ps1      integrated release build and license/source packaging
PREP_WPC_PROVIDER.ps1  prepares the locked WPC/nodriver runtime
PACKAGING_CHECKLIST.txt release/regression checklist
THIRD_PARTY_NOTICES.txt third-party component and license map
SOURCE_OFFER.txt       source-availability information for copyleft components
```

## Development notes

Install the Python dependencies from `requirements.txt` in the RR-V virtual environment.

The repository intentionally does **not** track generated or machine-local items such as:

- `.venv/`
- PyInstaller `build/`, `dist/`, and helper build output
- `resources/wpc-provider/runtime/`
- external runtime executables under `resources/tools/`
- logs, queue data, settings, cookies, and login credentials
- local release ZIP / Installer files

Prepare the exact WPC/nodriver runtime with:

```powershell
powershell -ExecutionPolicy Bypass -File .\PREP_WPC_PROVIDER.ps1
```

Create the complete 1.2.0 onedir release with:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_RELEASE.ps1
```

`BUILD_RELEASE.ps1` builds the Auth Helper and RR-V, places the helper beside `RR-V.exe`, verifies that yt-dlp / FFmpeg / FFprobe / Deno were not accidentally bundled, and collects release license/source materials.

Before a release, follow `PACKAGING_CHECKLIST.txt`.

## Authentication data

RR-V stores user settings and authentication data outside the source tree under the user's Windows AppData directories. Cookie files contain private login credentials and must never be committed or shared.

The `.gitignore` contains additional defensive rules in case such files are accidentally copied into the project folder.

## Browser connector

The Chromium extension source is under:

`resources/browser-extension/rrv-chromium/`

It is used by RR-V to send the current page or selected links to the running application, with Native Messaging as a fallback path when RR-V is fully stopped.

## Third-party software and licenses

See:

- `THIRD_PARTY_NOTICES.txt`
- `SOURCE_OFFER.txt`
- `auth_helper/LICENSE_NOTICE.txt`

The release build also generates a `licenses/` directory containing the exact available license/metadata files from the Python, PySide6/Qt, shiboken6, and locked WPC packages used by that build.

External yt-dlp / FFmpeg / Deno executables downloaded after installation remain governed by their respective upstream licenses.

## Project status

`1.2.0-community-beta` is the active community-beta development branch. The 1.1.3 tested baseline is preserved separately on `1.1.3-community-beta`.
