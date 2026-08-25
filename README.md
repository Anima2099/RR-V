# RR-V

**RR-V** is a Windows VOD downloader and local media-tools application built with Python and PySide6.

Current development version: **1.2.0 Community Beta**

> The RR-V core application is **source available** under the `RR-V Source Available License 1.0`. Personal use, use as a tool in professional work, source inspection, and private modifications are permitted. Redistribution and commercial exploitation of RR-V itself require prior written permission. Separately licensed components remain governed by their own licenses.

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

The community-beta Installer is built with Inno Setup 7 as a **per-user installation**. It does not request administrator elevation. The default installation directory is shown to the user and may be changed:

```text
%LOCALAPPDATA%\Programs\RR-V
```

RR-V is registered in Windows Installed apps and includes a normal uninstaller. During uninstall, the user can choose whether RR-V user data under LocalAppData/AppData should also be removed. User-data deletion is off by default; RR-V integration registry entries are removed regardless.

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
app/                   application settings, paths, stores, and shared app logic
auth_helper/           isolated browser-authentication helper source
controllers/           UI/controller coordination
core/                  core data models
installer/             Inno Setup script and Installer notes
services/              download, authentication, browser integration, media services
ui/                    main window, pages, dialogs, and widgets
workers/               background worker objects
resources/             icons, theme, browser connector, WPC runtime metadata
main.py                 application entry point
RR-V.spec               PyInstaller onedir build specification
RR-V-Auth-Helper.spec   separate Auth Helper build specification
BUILD_RELEASE.ps1       integrated release build and license/source packaging
BUILD_INSTALLER.ps1     verifies dist/RR-V and builds RR-V_Setup_1.2.0.exe
PREP_WPC_PROVIDER.ps1   prepares the locked WPC/nodriver runtime
PACKAGING_CHECKLIST.txt release/regression checklist
THIRD_PARTY_NOTICES.txt third-party component and license map
SOURCE_OFFER.txt        source-availability information for copyleft components
```

## Development notes

Install the Python dependencies from `requirements.txt` in the RR-V virtual environment.

The repository intentionally does **not** track generated or machine-local items such as:

- `.venv/`
- PyInstaller `build/`, `dist/`, and helper build output
- generated `installer-output/`
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

After installing Inno Setup 7, create the community-beta Installer with:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_INSTALLER.ps1
```

Expected output:

```text
installer-output\RR-V_Setup_1.2.0.exe
```

`BUILD_INSTALLER.ps1` verifies the release layout and license files again, rejects accidentally bundled external tools or Qt Virtual Keyboard, finds `ISCC.exe`, compiles the Installer, and prints its SHA-256 hash. See `installer/README.md` for the install/uninstall policy and smoke-test flow.

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

## License

### RR-V core

The RR-V core is distributed under the **RR-V Source Available License 1.0**. See [`LICENSE`](LICENSE) for the complete terms.

In short:

- Personal use is permitted.
- RR-V may be used as a tool in educational, research, creative, and professional work.
- Source inspection and private modifications for your own use are permitted.
- Sharing links to the official RR-V repository or official releases is permitted and encouraged.
- Redistribution of RR-V or modified versions requires prior written permission.
- Commercial exploitation of RR-V itself requires prior written permission.
- Separately licensed and third-party components remain governed by their own licenses.

RR-V is **source available**, not OSI-approved open-source software.

### 한국어 요약

RR-V 본체는 **RR-V Source Available License 1.0**에 따라 소스가 공개됩니다.

- 개인적인 사용이 허용됩니다.
- 교육, 연구, 창작 및 업무에서 RR-V를 도구로 사용하는 것이 허용됩니다.
- 소스 코드를 열람하거나 개인적인 용도로 수정하여 사용하는 것이 허용됩니다.
- 공식 RR-V 저장소 또는 공식 Release 링크를 공유하는 것은 허용되며 권장됩니다.
- RR-V 원본 또는 수정본을 재배포하려면 저작권자의 사전 서면 허가가 필요합니다.
- RR-V 자체를 판매, 유료 배포, 광고·구독 등 수익화 목적으로 이용하려면 사전 서면 허가가 필요합니다.
- 별도의 라이선스가 명시된 구성요소와 제3자 소프트웨어에는 각각의 라이선스가 우선 적용됩니다.

RR-V는 소스 코드를 확인할 수 있는 **Source Available** 소프트웨어이며, OSI가 정의하는 오픈소스 소프트웨어는 아닙니다.

The RR-V-specific source under `auth_helper/` is separately licensed under **AGPL-3.0-only**. Third-party components retain their respective upstream licenses.

## Project status

`1.2.0-community-beta` is the active community-beta development branch. The 1.1.3 tested baseline is preserved separately on `1.1.3-community-beta`.
