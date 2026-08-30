# RR-V Installer

RR-V 1.3.0 Community Beta uses Inno Setup 7 to build a per-user Windows Installer.

## Install model

- No administrator elevation is requested.
- Default install directory: `%LOCALAPPDATA%\Programs\RR-V`
- The destination page is always shown and the user may change the path.
- RR-V is registered in Windows Installed apps through Inno Setup's normal uninstaller entry.
- A Start Menu shortcut is created.
- The desktop shortcut is optional and unchecked by default.
- The Installer contains the complete `dist\RR-V` onedir package.
- yt-dlp, FFmpeg/FFprobe and Deno are not bundled. RR-V downloads those tools from their official distribution sources after launch.

## User data

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

`installer-output\RR-V_Setup_1.3.0.exe`

`BUILD_INSTALLER.ps1` reads `APP_VERSION` from `app\constants.py`, verifies that the Inno Setup version matches it, checks the required RR-V/license files, confirms external runtime tools and Qt Virtual Keyboard were not bundled, compiles the Installer, and prints the final SHA-256 hash.

## Installer smoke test

1. Confirm the destination page visibly shows `%LOCALAPPDATA%\Programs\RR-V` by default.
2. Install without administrator elevation.
3. Confirm RR-V appears in Windows Installed apps as version 1.3.0.
4. Confirm Start Menu shortcut works.
5. If selected, confirm the desktop shortcut works.
6. Launch RR-V and verify Program Information/license links.
7. Verify missing runtime-tool installation or existing-tool detection.
8. Verify a Chrome or Edge site login and one lightweight download.
9. Verify browser integration after registering it from RR-V.
10. Verify Windows-startup registration if enabled.
11. Uninstall once with user-data deletion unchecked and confirm `%LOCALAPPDATA%\RR-V` / `%APPDATA%\RR-V` survive.
12. Reinstall, then uninstall with user-data deletion checked and confirm both RR-V data directories are removed.
13. In both uninstall cases, confirm the RR-V Run value and Native Messaging host registry keys are removed.
