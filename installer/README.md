# RR-V Installer

RR-V uses Inno Setup 7 to build a per-user Windows Installer.

## Install model

- No administrator elevation is requested.
- Default install directory: `%LOCALAPPDATA%\Programs\RR-V`
- The destination page is always shown and the user may change the path.
- RR-V is registered in Windows Installed apps through Inno Setup's normal uninstaller entry.
- A Start Menu shortcut is created.
- The desktop shortcut is optional and unchecked by default.
- The Installer contains the complete `dist\RR-V` onedir package.
- yt-dlp, FFmpeg/FFprobe and Deno are not bundled. RR-V downloads those tools from their official distribution sources after launch.

## Clean upgrade model

When an existing RR-V installation is detected, the Installer shows an `RR-V 업데이트 옵션` page. Normal upgrade is intentionally conservative:

- The new application package is installed first.
- `BUILD_INSTALLER.ps1` generates `RRV_INSTALL_MANIFEST.txt` from the exact `dist\RR-V` payload included in the Installer.
- After the new package is in place, files under the selected RR-V application directory that are not present in the new manifest are removed as stale application files.
- Inno Setup `unins*` files are preserved so the existing uninstall log can be updated normally for the same RR-V `AppId`.
- Reparse points are never traversed by the stale-file cleaner.
- Clean-up runs only when an existing RR-V installation was detected and `RR-V.exe` was already present in the selected destination before installation. This avoids treating an unrelated user-selected folder as RR-V-owned content.

This makes an upgrade a clean replacement of RR-V program files rather than a simple overlay, while leaving user/runtime data outside the program directory untouched by default.

## Optional reset during upgrade

The update-options page contains one unchecked option:

`설정, 로그인, 프리셋 및 다운로드 도구도 초기화`

If it stays unchecked, RR-V user/runtime data is preserved. If the user explicitly checks it, the Installer removes RR-V-managed data after the new application files have been installed and before the optional post-install RR-V launch:

- `%LOCALAPPDATA%\RR-V`: downloaded tools, WPC/auth runtime, browser integration files, temporary local runtime state
- `%APPDATA%\RR-V`: settings, login cookies, logs, backups, queue/presets
- legacy RR-V settings under `HKCU\Software\RR-V`
- RR-V startup and Native Messaging registrations

Files downloaded by the user to their own video/subtitle folders are not in either RR-V data directory and are not touched by this option.

## Automatic update Installer location

RR-V downloads and SHA-256 verifies an automatic-update Installer under the Windows temporary directory, not under `%LOCALAPPDATA%\RR-V`. This keeps the verified Installer outside the data tree that an optional full reset may remove.

Older RR-V versions may have downloaded the first upgrading Installer into `%LOCALAPPDATA%\RR-V\updates`; Inno Setup's normal Setup Loader copies and runs Setup from the Windows temporary directory, so the 1.4 transition remains compatible. From the updated RR-V version onward, the source Installer is placed in Windows TEMP directly.

## Uninstall user data

RR-V runtime/user data remains separate from the installed application:

- `%LOCALAPPDATA%\RR-V`: downloaded tools, WPC/auth runtime, browser integration files, temporary local runtime state
- `%APPDATA%\RR-V`: settings, login cookies, logs, backups, queue/presets

During uninstall, RR-V always removes its installed application files and Windows integration registrations. A custom uninstall option lets the user choose whether the two RR-V data directories should also be deleted. The data-deletion checkbox is off by default.

If full user-data removal is selected, legacy RR-V registry settings under `HKCU\Software\RR-V` are also removed.

## Integration cleanup

Uninstall always removes:

- `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value `RR-V`
- Chrome Native Messaging host registration for `com.rrv.browser_bridge`
- Edge Native Messaging host registration for `com.rrv.browser_bridge`
- RR-V Native Messaging manifest under `%LOCALAPPDATA%\RR-V\browser-integration`
- stale RR-V external URL endpoint metadata

Browser extensions loaded manually in Chrome/Edge must still be removed from the browser by the user if they no longer want the extension itself.

## Build

First build the tested onedir package:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_RELEASE.ps1
```

Then build the Installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_INSTALLER.ps1
```

Expected output:

`installer-output\RR-V_Setup_<APP_VERSION>.exe`

`BUILD_INSTALLER.ps1` reads `APP_VERSION` from `app\constants.py`, verifies that the Inno Setup version matches it, checks the required RR-V/license files, confirms external runtime tools and Qt Virtual Keyboard were not bundled, generates the clean-up manifest, compiles the Installer, and prints the final SHA-256 hash.

## Installer smoke test

1. Confirm a fresh install does not show the `RR-V 업데이트 옵션` page.
2. Install without administrator elevation and verify the normal shortcuts/program registration.
3. Prepare an existing RR-V install with known settings, a preset/login state if appropriate, installed runtime tools, and a harmless stale sentinel file inside the RR-V application directory.
4. Run the new Installer over that installation with the reset option **unchecked**.
5. Confirm the stale sentinel file is removed from the application directory while `%LOCALAPPDATA%\RR-V` and `%APPDATA%\RR-V` survive.
6. Launch RR-V and verify the preserved settings/preset/login state and existing runtime tools are still recognized.
7. Verify one lightweight YouTube download and any relevant browser integration.
8. Re-create identifiable RR-V user/runtime data, then run the Installer again with `설정, 로그인, 프리셋 및 다운로드 도구도 초기화` **checked**.
9. Confirm `%LOCALAPPDATA%\RR-V` and `%APPDATA%\RR-V` are removed before RR-V's first post-install launch recreates only the normal fresh-start directories/settings.
10. Confirm old startup/Native Messaging registrations are removed by the reset path.
11. Confirm user-downloaded media in an external save folder is untouched in both upgrade modes.
12. Uninstall once with user-data deletion unchecked and confirm RR-V data survives.
13. Reinstall, then uninstall with user-data deletion checked and confirm both RR-V data directories are removed.
