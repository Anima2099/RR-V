<p align="center">
  <img src="docs/images/rr-v_banner.png" alt="RR-V banner" width="100%">
</p>

# RR-V

### Video Downloader & Media Tools for Windows

**RR-V**는 널리 사용되는 오픈소스 영상 다운로드 도구 **yt-dlp**를 복잡한 명령어 없이 쉽고 빠르게 사용할 수 있도록 만든 Windows용 비디오 다운로드 & 미디어 도구입니다.

**현재 버전: 1.4.0 Community Beta**

➡️ **[최신 버전 다운로드 · GitHub Releases](https://github.com/Anima2099/RR-V/releases)**

설치 파일은 GitHub Releases에서 `RR-V_Setup_1.4.0.exe` 형태로 배포합니다.

---

## 주요 기능

### 다운로드

- **yt-dlp 기반의 다양한 사이트 영상 다운로드**
- **MP4 · MKV · WebM** 컨테이너와 **H.264 · VP9 · AV1** 코덱 선택 지원
- **M4A · MP3 · Opus · FLAC** 오디오 다운로드 지원
- 썸네일 · 메타데이터 · 자막 저장 및 영상 파일 내장 지원
- 여러 URL 자동 감지, 재생목록/여러 주소 일괄 추가 및 원하는 항목 선별 다운로드
- 빠른 추가 후 자동 다운로드 옵션과 기존 순차 대기열 유지
- 실패 작업 필터, 전체 재시도 및 실패 항목 일괄 삭제
- 전체 · 완료 · 실패 목록 TXT 내보내기 / 불러오기
- 사용자 다운로드 프리셋 생성 · 수정 · 삭제 · 복제 및 기본 프리셋 지정
- 파일명 템플릿과 제목/채널명/영상 ID/사이트/해상도/업로드 날짜/재생시간/프리셋/코덱 토큰 조합
- 챕터 기준 분할 다운로드
- SponsorBlock 정보를 이용한 스폰서/광고 구간 챕터 표시

### 사이트 인증과 브라우저 연동

- YouTube · Instagram · TikTok RR-V 관리형 로그인
- Google Chrome · Microsoft Edge 인증 브라우저 지원
- Chrome / Edge용 **RR-V Browser Connector**
- RR-V 실행/트레이 상태에서는 빠른 로컬 연결, 완전 종료 상태에서는 Native Messaging 폴백
- 브라우저 링크 전송 시 대기열 추가 또는 자동 다운로드 선택

### 미디어 도구

- 로컬 미디어의 상세 영상/오디오/컨테이너 정보 확인
- **REMUX**를 이용한 재인코딩 없는 영상 컨테이너 변경
- 영상을 **WebP · GIF · APNG · AVIF** 애니메이션 이미지로 단일 / 일괄 변환
- 단일 및 일괄 영상 썸네일 교체
- 영상 프레임 스냅샷 제작
- 자막 관리 및 관련 미디어 도구

### 프로그램 관리

- **정식 / 베타 채널을 지원하는 RR-V 자체 업데이트 기능**
- yt-dlp / FFmpeg / FFprobe / Deno 상태 확인, 설치, 업데이트 및 복구
- 업데이트 시 기존 RR-V 프로그램 파일을 새 버전 기준으로 정리하는 Clean Upgrade
- 업데이트 시 사용자 선택에 따라 설정 · 로그인 · 프리셋 · 다운로드 도구 초기화 가능
- Light / Dark **Warm Sage** 테마

## 스크린샷

### 메인 인터페이스

![RR-V 메인 인터페이스](docs/images/rrv-main.jpg)

### 다운로드 & 일괄 추가

| 다운로드 목록 | 여러 주소 · 재생목록 일괄 추가 |
| :---: | :---: |
| ![RR-V 다운로드 목록](docs/images/rrv-download-list.jpg) | ![RR-V 일괄 추가](docs/images/rrv-batch-add.jpg) |

### 다크 모드 & 미디어 도구

| 다크 모드 | 미디어 도구 |
| :---: | :---: |
| ![RR-V 다크 모드](docs/images/rrv-dark.jpg) | ![RR-V 미디어 도구](docs/images/rrv-tools.jpg) |

> 일부 스크린샷은 이전 버전의 화면을 포함할 수 있습니다. 현재 기능과 메뉴 구조는 아래 안내를 기준으로 확인해 주세요.

## 설치 후 처음 할 일

RR-V를 처음 설치했다면 다운로드에 필요한 필수 구성요소를 준비해야 합니다.

1. RR-V를 실행합니다.
2. **설정 → 프로그램 관리 → 도구 및 리소스**로 이동합니다.
3. **필수 구성요소 설치**를 실행합니다.
4. 설치가 완료되면 영상 URL을 추가하여 사용할 수 있습니다.

RR-V는 `yt-dlp`, `FFmpeg / FFprobe`, `Deno` 실행 파일을 Installer에 포함하지 않습니다. 필요한 경우 각 프로젝트의 공식 배포처에서 다운로드하여 사용자의 RR-V 데이터 폴더에 설치합니다.

YouTube 인증과 PO Token 지원에 필요한 잠금된 WPC/nodriver 런타임은 별도로 관리됩니다.

## 설정 화면 구조

RR-V 1.4.0부터 설정 화면은 세 개의 큰 영역과 내부 탭으로 정리되어 있습니다.

- **기본 설정**
  - 일반 설정
  - 다운로드 설정
  - 다운로드 프리셋
- **사이트 연동**
  - 인증 관리
  - 확장 프로그램
- **프로그램 관리**
  - 도구 및 리소스
  - 백업 및 복구

`프로그램 관리`에 들어가면 `도구 및 리소스`가 먼저 열리며 도구 상태와 업데이트 여부를 확인합니다.

## 빠른 추가 자동 다운로드

**설정 → 기본 설정 → 다운로드 설정**에서 `빠른 추가 후 자동으로 다운로드 시작`을 선택할 수 있습니다.

기본값은 꺼짐입니다. 켜면 빠른 추가의 정보 확인이 끝난 뒤 기존 순차 대기열을 자동으로 시작합니다. 이미 다른 다운로드가 진행 중이거나 먼저 대기 중인 작업이 있다면 병렬 실행이나 새치기 없이 기존 목록 순서를 유지합니다.

## 프로그램 업데이트와 Clean Upgrade

RR-V는 **정식 / 베타 업데이트 채널**을 선택할 수 있으며, 새 버전이 있으면 GitHub Releases의 Installer를 내려받아 파일 크기와 SHA-256을 검증한 뒤 RR-V를 종료하고 설치 프로그램을 실행합니다.

기존 RR-V 위에 새 버전을 설치하면 프로그램 폴더는 새 버전에 포함된 파일 기준으로 정리됩니다. 기본 동작은 사용자 데이터를 유지하는 것입니다.

기존 설치가 감지된 경우 Installer의 `RR-V 업데이트 옵션`에서 다음 항목을 선택할 수 있습니다.

`설정, 로그인, 프리셋 및 다운로드 도구도 초기화`

이 옵션은 기본적으로 꺼져 있습니다. 선택하면 RR-V가 관리하는 설정, 로그인 정보, 프리셋, 로그, 백업, 다운로드 도구와 관련 런타임 데이터를 초기화합니다. 사용자가 별도의 다운로드 폴더에 저장한 영상/자막 등 일반 파일은 삭제하지 않습니다.

자세한 Installer 동작과 개발용 테스트 절차는 [`installer/README.md`](installer/README.md)를 참고해 주세요.

## 사이트 로그인

일부 영상은 로그인 또는 인증이 필요할 수 있습니다.

RR-V는 현재 다음 사이트의 자체 로그인 기능을 제공합니다.

**YouTube · Instagram · TikTok**

지원되는 로그인 브라우저는 **Google Chrome · Microsoft Edge**입니다.

**설정 → 사이트 연동 → 인증 관리**에서 로그인할 수 있습니다. RR-V의 전용 로그인 창에서 해당 사이트에 로그인하면 인증 정보를 저장하여 이후 정보 확인과 다운로드에 사용합니다.

> RR-V는 Google, Instagram 또는 TikTok의 비밀번호를 직접 입력받거나 저장하지 않습니다.

## 브라우저 확장 프로그램

RR-V에는 Chrome / Edge용 **RR-V Browser Connector**가 포함되어 있습니다.

확장 프로그램을 설치하면 영상 페이지에서 RR-V 아이콘을 누르거나 영상 링크의 오른쪽 클릭 메뉴를 사용하여 현재 URL을 RR-V 다운로드 목록으로 바로 보낼 수 있습니다.

설치 및 연결 방법은 **설정 → 사이트 연동 → 확장 프로그램**에서 확인할 수 있습니다.

### Browser Connector 동작

| 확장 아이콘 클릭 | 영상 링크에서 오른쪽 클릭 |
| :---: | :---: |
| ![RR-V Browser Connector 아이콘 전송](docs/images/rrv-browser-connector-demo1.webp) | ![RR-V Browser Connector 링크 전송](docs/images/rrv-browser-connector-demo2.webp) |

## 지원 환경

- **Windows 10 / Windows 11 · 64-bit**
- 사이트 인증 브라우저: **Google Chrome · Microsoft Edge**
- Browser Connector: Chromium 기반 Chrome / Edge 환경을 기본 지원

영상 사이트의 정책 또는 구조 변경, yt-dlp의 현재 지원 상태, 사용자 PC 및 네트워크 환경에 따라 일부 사이트의 동작이 달라질 수 있습니다.

## Community Beta

RR-V 1.4.0은 **Community Beta** 버전입니다.

설치와 업그레이드, 사용자 데이터 보존/초기화, 영상 다운로드, 빠른 추가 자동 다운로드, 사이트 인증, Browser Connector, 미디어 도구 및 자체 업데이트 등의 주요 동작은 실제 Windows 환경에서 테스트를 거쳤습니다.

문제를 발견했다면 GitHub Issues 또는 아래 연락처를 통해 알려주세요.

**Developer:** Anima2099  
**Email:** [anima2099@proton.me](mailto:anima2099@proton.me)

## 라이선스

RR-V 본체는 **RR-V Source Available License 1.0**에 따라 배포됩니다.

개인적인 사용, 소스 코드 열람 및 개인 목적의 수정이 허용되며, 교육 · 연구 · 창작 · 업무에서 RR-V를 하나의 도구로 사용하는 것도 허용됩니다.

다만 RR-V 또는 수정된 RR-V를 재배포하거나, RR-V 자체를 판매 · 유료 배포하거나 그 자체를 상업적으로 이용하려면 저작권자의 사전 서면 허가가 필요합니다.

- [RR-V Source Available License 1.0 · English](LICENSE)
- [RR-V Source Available License 1.0 · 한국어 번역본](LICENSE.ko-KR.txt)
- [Third-party Notices](THIRD_PARTY_NOTICES.txt)
- [Source Availability / Written Offer](SOURCE_OFFER.txt)

한국어 번역본은 이해를 돕기 위한 편의 번역이며, 영어 원문과 해석이 다른 경우 영어 `LICENSE`가 우선합니다.

RR-V는 **Source Available** 소프트웨어이며, OSI가 정의하는 오픈소스 소프트웨어는 아닙니다. RR-V Auth Helper와 제3자 구성요소에는 각각 별도의 라이선스가 적용됩니다.

## 프로젝트 링크

**GitHub:** https://github.com/Anima2099/RR-V  
**Developer:** Anima2099  
**Contact:** [anima2099@proton.me](mailto:anima2099@proton.me)

### 후원하기

**Buy Me a Coffee:** https://buymeacoffee.com/anima2099

*RR-V를 잘 사용하고 계신다면 커피 한 잔 부탁드립니다!*

---

# Developer / Technical Information

아래 내용은 RR-V의 소스 구조, 빌드 방식 및 제3자 구성요소의 배포 구조에 관한 개발자용 정보입니다.

## Distribution Model

RR-V uses a PyInstaller **onedir** layout.

```text
dist/RR-V/
  RR-V.exe
  RR-V-Auth-Helper.exe
  LICENSE.txt
  LICENSE.ko-KR.txt
  THIRD_PARTY_NOTICES.txt
  SOURCE_OFFER.txt
  licenses/
  _internal/
```

The Community Beta Installer is built with Inno Setup 7 as a **per-user installation**. It does not request administrator elevation. The default installation directory is shown to the user and may be changed:

```text
%LOCALAPPDATA%\Programs\RR-V
```

RR-V is registered in Windows Installed Apps and includes a normal uninstaller. During uninstall, the user can choose whether RR-V user data under LocalAppData/AppData should also be removed. User-data deletion is off by default; RR-V integration registry entries are removed regardless.

The RR-V Installer does **not** bundle these external executables:

- `yt-dlp.exe`
- `ffmpeg.exe`
- `ffprobe.exe`
- `deno.exe`

After RR-V is installed, missing required tools can be prepared from **설정 → 프로그램 관리 → 도구 및 리소스**. RR-V downloads those tools from their official distribution channels and stores them under the user's LocalAppData RR-V tools directory.

The YouTube WPC/browser-authentication runtime is a separate locked runtime and is bundled as Python source plus package metadata because it is required by RR-V authentication and YouTube PO-token support.

## Authentication Boundary

RR-V core does not import `nodriver` directly.

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

## Repository Layout

```text
app/                   application settings, paths, stores, and shared app logic
auth_helper/           isolated browser-authentication helper source
controllers/           UI/controller coordination
core/                  core data models
installer/             Inno Setup script and Installer notes
services/              download, authentication, browser integration, media services
ui/                    main window, pages, dialogs, widgets, and media-tool pages
workers/               background worker objects
resources/             icons, theme, browser connector, WPC runtime metadata
main.py                 application entry point
RR-V.spec               PyInstaller onedir build specification
RR-V-Auth-Helper.spec   separate Auth Helper build specification
BUILD_RELEASE.ps1       integrated release build and license/source packaging
BUILD_INSTALLER.ps1     verifies dist/RR-V and builds the versioned Installer
PREP_WPC_PROVIDER.ps1   prepares the locked WPC/nodriver runtime
PACKAGING_CHECKLIST.txt release/regression checklist
GITHUB_SETUP.md         GitHub Desktop / VS Code development setup guide
LICENSE                 authoritative RR-V Source Available License 1.0 text
LICENSE.ko-KR.txt       Korean convenience translation; English LICENSE controls
THIRD_PARTY_NOTICES.txt third-party component and license map
SOURCE_OFFER.txt        source-availability information for copyleft components
```

## Development Setup

The current GitHub Desktop / VS Code development setup, test flow, and build commands are documented in [`GITHUB_SETUP.md`](GITHUB_SETUP.md).

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

Run the self-tests with:

```powershell
python -m unittest discover -s tests -v
```

Create the current onedir release with:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_RELEASE.ps1
```

After installing Inno Setup 7, create the Installer with:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_INSTALLER.ps1
```

For RR-V 1.4.0 the expected output is:

```text
installer-output\RR-V_Setup_1.4.0.exe
```

`BUILD_RELEASE.ps1` builds the Auth Helper and RR-V, places the helper beside `RR-V.exe`, verifies that yt-dlp / FFmpeg / FFprobe / Deno were not accidentally bundled, and collects release license/source materials.

`BUILD_INSTALLER.ps1` verifies the release layout and license files again, rejects accidentally bundled external tools or Qt Virtual Keyboard, generates the install manifest used by Clean Upgrade, compiles the Installer, and prints its SHA-256 hash. See `installer/README.md` for the install/uninstall policy and smoke-test flow.

Before a release, follow `PACKAGING_CHECKLIST.txt`.

## Authentication Data

RR-V stores user settings and authentication data outside the source tree under the user's Windows AppData directories. Cookie files contain private login credentials and must never be committed or shared.

The `.gitignore` contains additional defensive rules in case such files are accidentally copied into the project folder.

## Browser Connector

The Chromium extension source is under:

`resources/browser-extension/rrv-chromium/`

It is used by RR-V to send the current page or selected links to the running application, with Native Messaging as a fallback path when RR-V is fully stopped.

## Third-party Software and Licenses

See:

- `THIRD_PARTY_NOTICES.txt`
- `SOURCE_OFFER.txt`
- `auth_helper/LICENSE_NOTICE.txt`

The release build also generates a `licenses/` directory containing the exact available license/metadata files from the Python, PySide6/Qt, shiboken6, and locked WPC packages used by that build.

The RR-V-specific source under `auth_helper/` is separately licensed under **AGPL-3.0-only**. Third-party components retain their respective upstream licenses.

External yt-dlp / FFmpeg / Deno executables downloaded after installation remain governed by their respective upstream licenses.

## Project Status

Version-specific development and release preparation may take place on version branches such as `1.4.0-community-beta`. The `main` branch is used as the public release source line, while previous tagged releases remain available through GitHub Releases and their preserved refs.
