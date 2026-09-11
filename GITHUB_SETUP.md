# RR-V Development Setup

This guide describes the current RR-V development workflow using **GitHub Desktop** and **Visual Studio Code** on Windows.

## 1. Clone the repository

1. Open **GitHub Desktop** and sign in to the GitHub account that has access to `Anima2099/RR-V`.
2. Choose **File > Clone repository**.
3. Select `Anima2099/RR-V` and choose a local parent folder.
4. After cloning, confirm the intended development branch in GitHub Desktop before making changes.
5. Use **Repository > Open in Visual Studio Code** to open the project.

## 2. Python virtual environment

RR-V expects a project-local virtual environment at:

```text
.venv\
```

If a new development machine needs a virtual environment, create one with the Python version intended for the current RR-V release environment, activate it, and install the pinned project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

Do not commit `.venv/` to Git.

## 3. Prepare the locked YouTube authentication runtime

RR-V keeps the WPC/nodriver support runtime outside Git because it is generated from the locked dependency set.

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\PREP_WPC_PROVIDER.ps1
```

The script recreates `resources\wpc-provider\runtime`, verifies the expected dependency set, removes Python cache files, and prepares the same runtime used by RR-V authentication and YouTube PO-token support.

## 4. Run RR-V from VS Code

With the project virtual environment active:

```powershell
python .\main.py
```

For normal development and smoke testing, use the VS Code terminal so errors remain visible.

## 5. Run self-tests

Before packaging or after meaningful changes, run:

```powershell
python -m unittest discover -s tests -v
```

Do not treat source/contract tests as a substitute for Windows smoke tests. UI, authentication, browser integration, tool installation, downloads, tray behavior, and Installer behavior should still be checked in the packaged application when relevant.

## 6. Build the onedir release

Completely exit RR-V first, including the system tray, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_RELEASE.ps1
```

The release builder:

- verifies RR-V version metadata;
- builds `RR-V-Auth-Helper.exe`;
- builds the PyInstaller onedir RR-V package;
- copies required license/source materials;
- verifies that yt-dlp / FFmpeg / FFprobe / Deno were not bundled accidentally;
- rejects forbidden Qt Virtual Keyboard payloads.

Expected release directory:

```text
dist\RR-V\
```

## 7. Build the Windows Installer

Install Inno Setup 7 on the build machine, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\BUILD_INSTALLER.ps1
```

The script reads the current `APP_VERSION`, verifies the Inno Setup version matches, generates the Clean Upgrade install manifest, compiles the Installer, and prints its SHA-256 hash.

For RR-V 1.4.0 the expected file is:

```text
installer-output\RR-V_Setup_1.4.0.exe
```

Before a public release, follow `PACKAGING_CHECKLIST.txt` and `installer/README.md`.

## 8. GitHub Desktop workflow

A conservative workflow is recommended:

1. **Fetch origin** before starting work.
2. Confirm the intended branch.
3. Review every changed file in GitHub Desktop.
4. Commit related changes together with a short descriptive message.
5. Push the branch.
6. Before release, compare the release branch with `main` and resolve any divergence deliberately instead of force-overwriting history.

## Files that must not be committed

The repository intentionally ignores generated or private machine-local data, including:

- `.venv/`
- `.vscode/`
- `build/`, `dist/`, and temporary helper build output
- `installer-output/`
- `resources/wpc-provider/runtime/`
- downloaded external runtime executables
- cookies, authentication data, settings, queues, logs, backups, and thumbnails from AppData
- local ZIP / 7z / RAR backups and Installer files

`.gitignore` is only a preventive filter for untracked files. It does not remove a secret that was already committed, so always review GitHub Desktop's changed-file list before committing.
