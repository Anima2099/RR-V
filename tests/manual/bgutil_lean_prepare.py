"""Stage03 developer-only lean BgUtils install experiment.

Create a *separate* locally installed candidate from the already verified
external provider. Never change the original provider or RR-V's runtime path.
No upstream source, native binaries, or credentials are committed to RR-V.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.paths import find_executable
from services import bgutil_http_service as bgutil

TARGET_NAME = "bgutil-stage03-lean-experiment"
MARKER = "rrv-lean-experiment.json"
INSTALL_TIMEOUT = 300


def install_command(deno: Path) -> list[str]:
    """Keep frozen upstream resolution and the approved canvas install script."""
    return [
        str(deno), "install", "--frozen", "--prod",
        "--node-modules-dir=auto", "--allow-scripts=npm:canvas",
        "--entrypoint", "src/main.ts",
    ]


def experiment_paths(local_appdata: Path) -> tuple[Path, Path]:
    configured = os.environ.get(bgutil.ENV_HOME, "").strip()
    original = (
        Path(configured).expanduser() if configured
        else local_appdata / "RR-V" / "bgutil-stage03-external"
    )
    candidate = local_appdata / "RR-V" / "diagnostics" / TARGET_NAME
    return original, candidate


def is_prepared(candidate: Path) -> bool:
    try:
        marker = json.loads((candidate / MARKER).read_text(encoding="utf-8"))
        if marker != {
            "schema": 1,
            "source_commit": bgutil.SOURCE_COMMIT,
            "method": "prod-entrypoint-frozen",
        }:
            return False
        return bgutil._validate_external_home(candidate)
    except (OSError, ValueError, TypeError):
        return False


def _copy_verified_source(source: Path, staging: Path) -> None:
    """Copy upstream files, but never duplicate the original installed modules."""
    server = source / "server"
    for base, dirs, files in os.walk(server, followlinks=False):
        dirs[:] = [name for name in dirs if name not in {"node_modules", "deno-cache"}]
        if any((Path(base) / name).is_symlink() for name in (*dirs, *files)):
            raise ValueError("linked-upstream-source")
    shutil.copytree(
        server, staging / "server",
        ignore=shutil.ignore_patterns("node_modules", "deno-cache", "__pycache__", ".git"),
    )
    shutil.copytree(source / "plugins", staging / "plugins")
    for name in ("LICENSE", "plugin.zip", "rrv-stage03.json"):
        shutil.copy2(source / name, staging / name)


def prepare(source: Path, candidate: Path, deno: Path | None) -> str:
    """Prepare a separate candidate; return privacy-safe status codes."""
    try:
        source = source.resolve()
        candidate = candidate.resolve()
        if source == candidate or source in candidate.parents or candidate in source.parents:
            return "source-target-overlap"
        if candidate.exists() or candidate.is_symlink():
            return "already-prepared" if is_prepared(candidate) else "target-exists-unverified"
        if not bgutil._validate_external_home(source):
            return "source-invalid"
        if deno is None or not deno.is_file():
            return "deno-missing"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Install at the *final* path. On Windows, npm native links and
            # Deno cache entries may retain absolute installation paths.
            candidate.mkdir()
        except FileExistsError:
            return "target-exists-unverified"
        completed = False
        try:
            _copy_verified_source(source, candidate)
            environment = os.environ.copy()
            environment.update({
                "DENO_DIR": str(candidate / "deno-cache"),
                "DENO_NO_PROMPT": "1",
                "DENO_NO_UPDATE_CHECK": "1",
                "FORCE_COLOR": "false",
            })
            result = subprocess.run(
                install_command(deno), cwd=str(candidate / "server"),
                env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=INSTALL_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return "deno-install-failed"
            if not (candidate / "server" / "node_modules").is_dir():
                return "node-modules-missing"
            if not bgutil._validate_external_home(candidate):
                return "candidate-invalid"
            (candidate / MARKER).write_text(
                json.dumps({
                    "schema": 1,
                    "source_commit": bgutil.SOURCE_COMMIT,
                    "method": "prod-entrypoint-frozen",
                }), encoding="utf-8",
            )
            completed = True
            return "prepared"
        except subprocess.TimeoutExpired:
            return "deno-install-timeout"
        except (OSError, ValueError, shutil.Error):
            return "candidate-setup-failed"
        finally:
            if not completed:
                shutil.rmtree(candidate, ignore_errors=True)
    except (OSError, ValueError):
        return "path-or-source-error"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a separate lean BgUtils test installation")
    parser.add_argument("--verify", action="store_true", help="Only verify the existing candidate")
    args = parser.parse_args(argv)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        print("BGUTIL LEAN: localappdata-unavailable")
        return 1
    source, candidate = experiment_paths(Path(local))
    if args.verify:
        status = "verified" if is_prepared(candidate) else "not-prepared"
    else:
        status = prepare(source, candidate, find_executable("deno.exe"))
    print(f"BGUTIL LEAN: {status}")
    print("Original BgUtils installation and RR-V runtime were not changed.")
    return 0 if status in {"prepared", "already-prepared", "verified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
