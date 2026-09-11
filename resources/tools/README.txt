RR-V runtime tools directory

Starting with RR-V 1.2.0, third-party executable tools are NOT bundled with the RR-V package.
Do not place release seed binaries in this directory for packaging.

RR-V installs and manages these tools at runtime under:

  %LOCALAPPDATA%\RR-V\tools

Managed runtime tools:

  yt-dlp.exe
  ffmpeg.exe
  ffprobe.exe
  deno.exe

When a required tool is missing, RR-V shows the missing state under:

  설정 > 프로그램 관리 > 도구 및 리소스

The primary action becomes "필수 구성요소 설치" and RR-V downloads the required tool from its upstream distribution source.
Existing tools can be checked and refreshed through the same screen.

The files in %LOCALAPPDATA%\RR-V\tools are runtime-managed copies and are not Git repository content.

YouTube authentication/WPC support is prepared separately and is not part of this runtime tools directory.
