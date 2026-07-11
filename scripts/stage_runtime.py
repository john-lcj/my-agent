#!/usr/bin/env python3
"""Create a code-only Captain runtime tree from an explicit allowlist."""
from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
from pathlib import Path

RUNTIME_DIRS = (
    "agents",
    "browser_runtime",
    "capabilities",
    "channels",
    "connectors",
    "core",
    "frontend",
    "governance",
    "license_client",
    "llm",
    "memory",
    "observability",
    "scheduler",
    "server",
    "skills",
)
RUNTIME_FILES = (
    "config.py",
    "main.py",
    "mcp_servers.json.example",
    "persona.yaml",
    "pyproject.toml",
    "VERSION",
    "LICENSE",
)
PRESERVED_STATE = {".env", ".venv", "data", "logs", "runtime", "uploads"}
IGNORED_NAMES = {"__pycache__", ".DS_Store", ".pytest_cache"}
IGNORED_PATTERNS = ("*.pyc", "*.pyo", "*.md", "*.pem", "*.github_token")


def _ignored(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in IGNORED_NAMES
        or any(fnmatch.fnmatch(name, pattern) for pattern in IGNORED_PATTERNS)
    }


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def stage(source: Path, destination: Path, *, preserve_state: bool) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("source and destination must differ")
    destination.mkdir(parents=True, exist_ok=True)

    preserved = PRESERVED_STATE if preserve_state else set()
    for child in list(destination.iterdir()):
        if child.name in preserved:
            continue
        _remove(child)

    for rel in RUNTIME_DIRS:
        src = source / rel
        if not src.is_dir():
            raise FileNotFoundError(f"required runtime directory is missing: {src}")
        dst = destination / rel
        if dst.exists():
            _remove(dst)
        shutil.copytree(src, dst, symlinks=True, ignore=_ignored)

    for rel in RUNTIME_FILES:
        src = source / rel
        if not src.is_file():
            raise FileNotFoundError(f"required runtime file is missing: {src}")
        shutil.copy2(src, destination / rel)

    for state_dir in ("data", "logs", "uploads"):
        (destination / state_dir).mkdir(exist_ok=True)

    forbidden = [
        path
        for path in destination.rglob("*.md")
        if path.is_file() and path.relative_to(destination).parts[0] not in preserved
    ]
    nested_desktop = destination / "desktop"
    if forbidden or nested_desktop.exists():
        raise RuntimeError(
            "runtime staging validation failed: "
            f"markdown={len(forbidden)} nested_desktop={nested_desktop.exists()}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--preserve-state", action="store_true")
    args = parser.parse_args()
    stage(
        Path(args.source),
        Path(args.destination),
        preserve_state=args.preserve_state,
    )
    print(f"runtime staged: {Path(args.destination).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
