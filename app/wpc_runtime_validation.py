"""Checks the vendored WPC/nodriver Python sources without importing their dependencies.

The Windows nodriver 0.50.3 wheel can contain an unencoded CP1252 +/- sign
(0xB1) in a comment in cdp/network.py. Python assumes UTF-8 and rejects the
whole WPC plugin at import time. Limit repairs to that known location, rather
than silently converting or modifying unrelated third-party source files.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


_REQUIRED_SOURCES = (
    Path("yt_dlp_plugins/extractor/getpot_wpc.py"),
    Path("nodriver/__init__.py"),
    Path("nodriver/cdp/network.py"),
)


def repair_nodriver_network_encoding(runtime_dir: Path) -> int:
    """Replace only invalid standalone CP1252 0xB1 bytes in network.py comments."""
    network = Path(runtime_dir) / "nodriver" / "cdp" / "network.py"
    data = network.read_bytes()
    repaired = data
    count = 0
    while True:
        try:
            repaired.decode("utf-8", errors="strict")
            break
        except UnicodeDecodeError as error:
            line_start = repaired.rfind(b"\n", 0, error.start) + 1
            before = repaired[line_start:error.start]
            line_number = repaired.count(b"\n", 0, error.start) + 1
            if repaired[error.start] != 0xB1 or b"#" not in before:
                raise ValueError(
                    f"Unexpected non-UTF-8 source at {network}:{line_number}; "
                    "only the known nodriver 0xB1 comment bug may be repaired"
                ) from error
            repaired = repaired[:error.start] + b"\xc2\xb1" + repaired[error.start + 1:]
            count += 1
            if count > 16:
                raise ValueError(f"Too many invalid bytes in {network}; refusing to patch")

    if count:
        network.write_bytes(repaired)
    return count


def validate_wpc_source_tree(runtime_dir: Path) -> int:
    """Strict UTF-8 and Python syntax validation; does not create .pyc files."""
    root = Path(runtime_dir)
    for relative in _REQUIRED_SOURCES:
        if not (root / relative).is_file():
            raise ValueError(f"Missing WPC runtime source: {relative}")
    paths = sorted(root.rglob("*.py"))
    if not paths:
        raise ValueError("No WPC Python source files found")
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8-sig", errors="strict")
            compile(source, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as error:
            raise ValueError(f"Invalid WPC runtime source: {path}: {error}") from error
    return len(paths)


def wpc_critical_sources_valid(runtime_dir: Path) -> bool:
    """Fast, offline syntax check for the sources implicated in WPC load failures."""
    root = Path(runtime_dir)
    for relative in _REQUIRED_SOURCES:
        path = root / relative
        try:
            source = path.read_text(encoding="utf-8-sig", errors="strict")
            compile(source, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError):
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate WPC source before packaging")
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("--repair", action="store_true", help="Repair known 0xB1 comments first")
    args = parser.parse_args(argv)
    try:
        patches = repair_nodriver_network_encoding(args.runtime_dir) if args.repair else 0
        count = validate_wpc_source_tree(args.runtime_dir)
    except (OSError, ValueError) as error:
        print(f"WPC source validation FAILED: {error}", file=sys.stderr)
        return 1
    print(f"WPC source validation OK: {count} Python files, {patches} repaired bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
