# RR-V Auth Helper

RR-V Auth Helper is the isolated browser-authentication component used by RR-V.

## Boundary

The RR-V core application does not import `nodriver` directly. Instead it launches this helper as a separate process and exchanges a small JSON-lines protocol consisting of status messages and one final authentication result.

The helper is responsible for:

- launching the selected Chrome or Edge authentication window through `nodriver`;
- detecting completion of YouTube, Instagram, or TikTok login;
- exporting the matching Netscape cookie file;
- returning only a compact result record to RR-V.

RR-V core remains responsible for its UI, settings, queue, downloads, media tools, and storage paths.

## Runtime

During development the helper is launched with the current Python interpreter. A packaged RR-V build provides a separate `RR-V-Auth-Helper.exe` beside `RR-V.exe`.

The helper receives the isolated WPC/nodriver runtime directory explicitly from RR-V. It does not import RR-V application modules.

## License

The RR-V-specific source code in this `auth_helper` directory is licensed under **GNU Affero General Public License v3.0 only (AGPL-3.0-only)**.

See `LICENSE_NOTICE.txt` in this directory for the component license notice. `nodriver` is independently distributed under GNU AGPL v3.0 and retains its own copyright and license notices.

The RR-V release build copies this helper source and build specification into the release `licenses/RR-V-Auth-Helper-source/` directory so recipients have the preferred source form even when the main RR-V repository is not yet publicly accessible.

The bundled nodriver source is also present in RR-V's WPC runtime as Python source.

This helper license applies to the helper component. It does not, by itself, grant an open-source redistribution license to the separately developed RR-V core application.

For the complete distribution map and source-availability information, see the repository-root `THIRD_PARTY_NOTICES.txt` and `SOURCE_OFFER.txt` files.
