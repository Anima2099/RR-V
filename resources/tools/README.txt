RR-V 1.1.2 packaging seed tools

Final one-file packaging requires these four explicit release binaries in this folder:

  yt-dlp.exe   (latest tested Nightly build)
  ffmpeg.exe
  ffprobe.exe
  deno.exe     (Deno 2.3.0 or newer; current tested version recommended)

RR-V.spec intentionally stops the build if any of them is missing.
They are bundled as seed/recovery copies only.
At runtime RR-V copies missing tools to:

  %LOCALAPPDATA%\RR-V\tools

RR-V then executes only the LocalAppData copies, so yt-dlp Nightly updates,
Deno updates, and tool replacement persist independently of the one-file executable.

YouTube support in RR-V 1.1.2:
- yt-dlp uses its current default YouTube client selection.
- Deno is supplied to yt-dlp as its JavaScript runtime for YouTube challenges.
- RR-V-managed YouTube login is the primary authentication method.
- The advanced cookie folder remains available as a manual fallback.
- WPC/nodriver support is prepared separately with PREP_WPC_PROVIDER.ps1.

For public distribution, create/review THIRD_PARTY_NOTICES.txt and preserve
the exact license/source information that corresponds to the binaries placed here.
