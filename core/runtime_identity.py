"""Release identity and runtime diagnostics shared by packaging and the app."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_STAMP_FILE = ".captain_bundle_stamp"
BUNDLE_STAMP_SCHEMA = 1
RUNTIME_SCHEMA_VERSION = 1
VERSION_CONTRACT_VERSION = 1
TRUSTED_BUNDLE_VALUES = {"platform-signed", "tauri-signed"}
RUNTIME_DIRS = {
    "agents", "capabilities", "channels", "connectors", "core", "frontend",
    "governance", "license_client", "llm", "memory", "observability",
    "scheduler", "server", "skills",
}
RUNTIME_FILES = {
    "config.py", "main.py", "mcp_servers.json.example", "persona.yaml",
    "pyproject.toml", "VERSION", "LICENSE",
}


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version(root: str | None = None) -> str:
    path = os.path.join(root or project_root(), "VERSION")
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def parse_bundle_stamp(root_or_path: str | None = None) -> dict[str, str]:
    raw = root_or_path or project_root()
    path = raw if os.path.isfile(raw) else os.path.join(raw, BUNDLE_STAMP_FILE)
    values: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip():
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def _hash_files(root: str, relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    base = Path(root)
    for rel in sorted(relative_paths):
        path = base / rel
        if not path.is_file():
            continue
        digest.update(rel.replace(os.sep, "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def frontend_asset_hash(root: str | None = None) -> str:
    base = Path(root or project_root())
    front = base / "frontend"
    if not front.is_dir():
        return ""
    rels = [str(path.relative_to(base)) for path in front.rglob("*") if path.is_file()]
    return _hash_files(str(base), rels)


def runtime_source_hash(root: str | None = None) -> str:
    base = Path(root or project_root())
    rels: list[str] = []
    for dirname in sorted(RUNTIME_DIRS):
        directory = base / dirname
        if not directory.is_dir():
            continue
        rels.extend(
            str(path.relative_to(base))
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix not in {".pyc", ".pyo", ".md"}
            and path.name != ".DS_Store"
            and not path.name.endswith((".pem", ".github_token"))
            and "__pycache__" not in path.parts
        )
    rels.extend(name for name in sorted(RUNTIME_FILES) if (base / name).is_file())
    return _hash_files(str(base), rels)


def _git_commit(root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _git_dirty(root: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", root, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            if not line.startswith("?? "):
                return True
            rel = line[3:].strip().strip('"').replace("\\", "/")
            top = rel.split("/", 1)[0]
            if top in RUNTIME_DIRS or rel in RUNTIME_FILES:
                return True
        return False
    except Exception:
        return False


def running_commit(root: str | None = None) -> str:
    root = root or project_root()
    stamp = parse_bundle_stamp(root)
    return stamp.get("commit") or stamp.get("git") or _git_commit(root)


def instance_id(log_dir: str) -> str:
    real = os.path.realpath(os.path.expanduser(log_dir))
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]


def database_schema_versions(log_dir: str) -> dict[str, int]:
    result: dict[str, int] = {"runtime": RUNTIME_SCHEMA_VERSION}
    for name in ("tasks", "missions", "sessions", "memory", "vault", "users"):
        path = os.path.join(log_dir, f"{name}.db")
        if not os.path.isfile(path):
            continue
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                row = conn.execute("PRAGMA user_version").fetchone()
            result[name] = int(row[0] if row else 0)
        except Exception:
            result[name] = -1
    return result


def stamp_integrity_valid(stamp: dict[str, str]) -> bool:
    expected = stamp.get("manifest_hash", "")
    if not expected:
        return False
    payload = {k: v for k, v in stamp.items() if k != "manifest_hash"}
    canonical = "".join(f"{key}={payload[key]}\n" for key in sorted(payload))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() == expected


def runtime_diagnostics(root: str, log_dir: str) -> dict:
    stamp = parse_bundle_stamp(root)
    actual_frontend_hash = frontend_asset_hash(root)
    stamped_frontend_hash = stamp.get("frontend_hash", "")
    actual_source_hash = runtime_source_hash(root)
    stamped_source_hash = stamp.get("source_hash", "")
    return {
        "version": read_version(root),
        "commit": running_commit(root),
        "instance_id": instance_id(log_dir),
        "bundle_stamp": stamp,
        "bundle_stamp_valid": stamp_integrity_valid(stamp) if stamp else False,
        "bundle_trusted": stamp.get("trust", "") in TRUSTED_BUNDLE_VALUES,
        "frontend_asset_hash": actual_frontend_hash,
        "frontend_matches_bundle": bool(
            stamped_frontend_hash and stamped_frontend_hash == actual_frontend_hash
        ),
        "runtime_source_hash": actual_source_hash,
        "runtime_matches_bundle": bool(
            stamped_source_hash and stamped_source_hash == actual_source_hash
        ),
        "database_schema": database_schema_versions(log_dir),
    }


def _regex_version(path: Path, pattern: str) -> str:
    try:
        match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
        return match.group(1) if match else ""
    except OSError:
        return ""


def version_contract(root: str | None = None) -> dict[str, str]:
    base = Path(root or project_root())
    values = {
        "VERSION": read_version(str(base)),
        "pyproject.toml": _regex_version(base / "pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        "desktop/package.json": "",
        "desktop/src-tauri/tauri.conf.json": "",
        "desktop/src-tauri/Cargo.toml": _regex_version(
            base / "desktop/src-tauri/Cargo.toml", r'^version\s*=\s*"([^"]+)"'
        ),
    }
    for rel, key_path in (
        ("desktop/package.json", ("version",)),
        ("desktop/src-tauri/tauri.conf.json", ("package", "version")),
    ):
        try:
            value = json.loads((base / rel).read_text(encoding="utf-8"))
            for key in key_path:
                value = value[key]
            values[rel] = str(value)
        except Exception:
            values[rel] = ""
    return values


def validate_version_contract(root: str | None = None) -> tuple[bool, dict[str, str]]:
    values = version_contract(root)
    expected = values["VERSION"]
    return bool(expected and all(value == expected for value in values.values())), values


def build_bundle_stamp(
    root: str,
    *,
    target_platform: str,
    trust: str,
    commit: str | None = None,
    built_at: str | None = None,
) -> dict[str, str]:
    ok, versions = validate_version_contract(root)
    if not ok:
        detail = ", ".join(f"{key}={value or '<missing>'}" for key, value in versions.items())
        raise ValueError(f"version contract mismatch: {detail}")
    resolved_commit = commit or _git_commit(root) or "unknown"
    dirty = _git_dirty(root)
    if dirty and trust in TRUSTED_BUNDLE_VALUES and os.environ.get(
        "CAPTAIN_ALLOW_DIRTY_BUNDLE", ""
    ) != "1":
        raise ValueError("refusing to mark a dirty checkout as a signed release bundle")
    if dirty and not resolved_commit.endswith("+dirty"):
        resolved_commit += "+dirty"
    payload = {
        "stamp_schema": str(BUNDLE_STAMP_SCHEMA),
        "contract_version": str(VERSION_CONTRACT_VERSION),
        "schema_version": str(RUNTIME_SCHEMA_VERSION),
        "version": versions["VERSION"],
        "built_at": built_at or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "commit": resolved_commit,
        "platform": target_platform,
        "architecture": platform.machine() or "unknown",
        "trust": trust,
        "frontend_hash": frontend_asset_hash(root),
        "source_hash": runtime_source_hash(root),
    }
    canonical = "".join(f"{key}={payload[key]}\n" for key in sorted(payload))
    payload["manifest_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def write_bundle_stamp(path: str, values: dict[str, str]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    content = "".join(f"{key}={values[key]}\n" for key in sorted(values))
    Path(path).write_text(content, encoding="utf-8")
