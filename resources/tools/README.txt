RR-V 1.2.0 runtime tools directory

Starting with RR-V 1.2.0, third-party executable tools are NOT bundled with the RR-V package.
Do not place release seed binaries in this directory for packaging.

RR-V installs and manages these tools at runtime under:

  %LOCALAPPDATA%\RR-V\tools

Managed runtime tools:

  yt-dlp.exe
  ffmpeg.exe
  ffprobe.exe
  deno.exe

When a required tool is missing, Settings > Tools & Resources shows
"필수 구성요소 설치" and downloads the required tool from its upstream distribution source.
Existing tools can be refreshed through the same Tools & Resources screen.

The files in %LOCALAPPDATA%\RR-V\tools are runtime-managed copies and are not Git repository content.

YouTube authentication/WPC support is prepared separately and is not part of this runtime tools directory.
