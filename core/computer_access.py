"""Runtime computer access mode and macOS permission diagnostics."""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile


WORKSPACE_ACCESS = "workspace"
FULL_ACCESS = "full"
_BASE_WORKSPACE_ROOT = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip()


def normalize_access_mode(value: str | None) -> str:
    return FULL_ACCESS if str(value or "").strip().lower() == FULL_ACCESS else WORKSPACE_ACCESS


def apply_computer_access_mode(value: str | None) -> str:
    mode = normalize_access_mode(value)
    if mode == FULL_ACCESS:
        os.environ["CAPTAIN_FULL_COMPUTER_ACCESS"] = "1"
    else:
        os.environ.pop("CAPTAIN_FULL_COMPUTER_ACCESS", None)
        if _BASE_WORKSPACE_ROOT:
            os.environ["AGENT_WORKSPACE_ROOT"] = _BASE_WORKSPACE_ROOT
        else:
            os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    return mode


def full_computer_access_enabled() -> bool:
    return os.environ.get("CAPTAIN_FULL_COMPUTER_ACCESS", "") == "1"


def computer_permission_status() -> dict:
    status = {
        "platform": platform.system().lower(),
        "supported": platform.system() == "Darwin",
        "accessibility": False,
        "screen_recording": False,
    }
    if platform.system() != "Darwin":
        return status
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get UI elements enabled'],
            capture_output=True, text=True, timeout=5,
        )
        status["accessibility"] = result.returncode == 0 and result.stdout.strip().lower() == "true"
    except (OSError, subprocess.SubprocessError):
        pass
    path = ""
    try:
        fd, path = tempfile.mkstemp(prefix="captain-screen-check-", suffix=".png")
        os.close(fd)
        os.unlink(path)
        result = subprocess.run(
            ["screencapture", "-x", "-t", "png", path],
            capture_output=True, text=True, timeout=8,
        )
        status["screen_recording"] = (
            result.returncode == 0 and os.path.isfile(path) and os.path.getsize(path) > 0
        )
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
    return status


def open_macos_privacy_settings(kind: str) -> None:
    pages = {
        "accessibility": "Privacy_Accessibility",
        "screen_recording": "Privacy_ScreenCapture",
        "full_disk": "Privacy_AllFiles",
    }
    page = pages.get(str(kind or "").strip())
    if platform.system() != "Darwin" or not page:
        raise ValueError("unsupported macOS privacy settings page")
    subprocess.Popen(["open", f"x-apple.systempreferences:com.apple.preference.security?{page}"])
