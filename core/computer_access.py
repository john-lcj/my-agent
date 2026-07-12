"""Runtime computer access mode and macOS permission diagnostics."""
from __future__ import annotations

import ctypes
import os
import platform
import subprocess


WORKSPACE_ACCESS = "workspace"
FULL_ACCESS = "full"
AUTONOMOUS_ACCESS = "autonomous"
_BASE_WORKSPACE_ROOT = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip()


def normalize_access_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {WORKSPACE_ACCESS, FULL_ACCESS, AUTONOMOUS_ACCESS} else WORKSPACE_ACCESS


def apply_computer_access_mode(value: str | None) -> str:
    mode = normalize_access_mode(value)
    if mode in {FULL_ACCESS, AUTONOMOUS_ACCESS}:
        os.environ["CAPTAIN_FULL_COMPUTER_ACCESS"] = "1"
    else:
        os.environ.pop("CAPTAIN_FULL_COMPUTER_ACCESS", None)
        if _BASE_WORKSPACE_ROOT:
            os.environ["AGENT_WORKSPACE_ROOT"] = _BASE_WORKSPACE_ROOT
        else:
            os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    if mode == AUTONOMOUS_ACCESS:
        os.environ["CAPTAIN_AUTONOMOUS_ACCESS"] = "1"
    else:
        os.environ.pop("CAPTAIN_AUTONOMOUS_ACCESS", None)
    return mode


def full_computer_access_enabled() -> bool:
    return os.environ.get("CAPTAIN_FULL_COMPUTER_ACCESS", "") == "1"


def autonomous_computer_access_enabled() -> bool:
    return os.environ.get("CAPTAIN_AUTONOMOUS_ACCESS", "") == "1"


def _macos_accessibility_trusted() -> bool:
    try:
        framework = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        check = framework.AXIsProcessTrusted
        check.argtypes = []
        check.restype = ctypes.c_bool
        return bool(check())
    except (AttributeError, OSError):
        return False


def _macos_screen_capture_trusted() -> bool:
    try:
        framework = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        check = framework.CGPreflightScreenCaptureAccess
        check.argtypes = []
        check.restype = ctypes.c_bool
        return bool(check())
    except (AttributeError, OSError):
        return False


def computer_permission_status() -> dict:
    status = {
        "platform": platform.system().lower(),
        "supported": platform.system() == "Darwin",
        "accessibility": False,
        "screen_recording": False,
    }
    if platform.system() != "Darwin":
        return status
    # These preflight APIs are read-only. Unlike screencapture, osascript, or
    # CGRequestScreenCaptureAccess, they never display an authorization prompt.
    status["accessibility"] = _macos_accessibility_trusted()
    status["screen_recording"] = _macos_screen_capture_trusted()
    return status


def open_macos_privacy_settings(kind: str) -> None:
    pages = {
        "accessibility": "Privacy_Accessibility",
        "screen_recording": "Privacy_ScreenCapture",
        "full_disk": "Privacy_AllFiles",
    }
    kind = str(kind or "").strip()
    page = pages.get(kind)
    if platform.system() != "Darwin" or not page:
        raise ValueError("unsupported macOS privacy settings page")
    # Opening Settings is the only behavior here. Never attempt a protected
    # operation in the background because macOS may repeatedly prompt for it.
    modern = f"x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?{page}"
    subprocess.Popen(["open", modern])
