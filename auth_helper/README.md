# RR-V Auth Helper

RR-V Auth Helper is the isolated browser-authentication component used by RR-V.

## Boundary

The RR-V core application does not import `nodriver` directly. Instead it launches this helper as a separate process and exchanges a small JSON-lines protocol consisting of status messages and one final authentication result.

The helper is responsible for:

- launching the selected Chromium browser through `nodriver`;
- detecting completion of YouTube, Instagram, or TikTok login;
- exporting the matching Netscape cookie file;
- returning only a compact result record to RR-V.

RR-V remains responsible for its UI, settings, queue, downloads, media tools, and storage paths.

## Runtime

During development the helper is launched with the current Python interpreter. A packaged RR-V build is expected to provide a separate `RR-V-Auth-Helper.exe` beside `RR-V.exe`.

The helper receives the WPC/nodriver runtime directory explicitly from RR-V. It does not import RR-V application modules.

## License boundary

This helper is intentionally separated so that its source and license can be distributed independently under terms compatible with the AGPL-licensed `nodriver` dependency. The RR-V core communicates with it only through the process boundary and the small JSON-lines protocol described above.

The final distribution package must include the applicable helper license and third-party license notices before public release.
