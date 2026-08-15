# RR-V: first GitHub upload

This guide assumes that the empty private GitHub repository `Anima2099/RR-V` already exists.

## Safest first upload with GitHub Desktop

1. Keep the existing RR-V development folder untouched as the safety copy.
2. Open **GitHub Desktop** and sign in to the GitHub account that owns `Anima2099/RR-V`.
3. Choose **File > Clone repository**.
4. Select the existing `RR-V` repository from the GitHub.com list and choose a local parent folder.
5. GitHub Desktop creates a new local `RR-V` folder already connected to the empty GitHub repository.
6. Copy the **contents** of `RR-V_1.1.2_GitHub_Ready` into that newly cloned `RR-V` folder.
7. Return to GitHub Desktop. Review the changed-files list before committing.

### The first commit should include

- Python source folders and files
- `resources` source/assets except ignored generated runtime/binaries
- `RR-V.spec`
- `RR-V.version_info.txt`
- `requirements.txt`
- `PACKAGING_CHECKLIST.txt`
- `PREP_WPC_PROVIDER.ps1`
- `.gitignore`
- `.gitattributes`
- `README.md`
- `GITHUB_SETUP.md`

### It should NOT include

- `.venv/`
- `.vscode/`
- `build/` or `dist/`
- `resources/wpc-provider/runtime/`
- `resources/tools/*.exe`
- cookies or authentication files
- settings, queues, logs, backups, or thumbnails from AppData
- ZIP / 7z / RAR backup archives

8. Use a first commit message such as:

   `RR-V 1.1.2 release baseline`

9. Click **Commit to main**.
10. Click **Push origin**.
11. Open the GitHub repository in the browser and confirm that the ignored folders/files are absent.

## Important safety rule

`.gitignore` prevents matching files from being added to Git when they are untracked. It is not a vault and it does not erase a secret that has already been committed. Always review the GitHub Desktop file list before the first push, especially after authentication or packaging work.
