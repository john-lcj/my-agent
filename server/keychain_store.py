"""macOS Keychain helpers for Captain secrets.

The desktop app should not keep long-lived model keys or access tokens in
plain JSON/.env files.  This module uses the system `security` CLI so the
Python backend can work without extra native dependencies.  It is intentionally
quiet and falls back to file/env storage when Keychain is unavailable.
"""
from __future__ import annotations

import os
import platform
import subprocess

SERVICE = os.environ.get("CAPTAIN_KEYCHAIN_SERVICE", "club.irestart.captain")


def is_available() -> bool:
    if platform.system() != "Darwin":
        return False
    if os.environ.get("CAPTAIN_USE_KEYCHAIN", "").strip() == "0":
        return False
    return True


def should_use_for_path(path: str = "") -> bool:
    """Use Keychain for packaged macOS app data, or when explicitly enabled."""
    if not is_available():
        return False
    if os.environ.get("CAPTAIN_USE_KEYCHAIN", "").strip() == "1":
        return True
    if os.environ.get("CAPTAIN_DESKTOP", "").strip() == "1":
        return True
    return "Library/Application Support/Captain" in (path or "")


def get_secret(account: str) -> str:
    if not is_available() or not account:
        return ""
    try:
        res = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def set_secret(account: str, value: str) -> bool:
    if not is_available() or not account:
        return False
    value = value or ""
    try:
        res = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", value],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return res.returncode == 0


def delete_secret(account: str) -> bool:
    if not is_available() or not account:
        return False
    try:
        res = subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE, "-a", account],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    # `security` returns non-zero when the item does not exist; treat that as ok.
    return res.returncode == 0 or "could not be found" in (res.stderr or "").lower()


def secret_ref(kind: str, name: str) -> str:
    return f"{kind}:{name}"
