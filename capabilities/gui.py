"""macOS computer observation and GUI control with audited screenshots."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from config import Config
from core.computer_access import computer_permission_status
from core.types import CapabilityResult, Risk

_TRACE_DIR = os.path.join(Config.LOG_DIR, "gui_trace")


class GUIObserve:
    name = "gui.observe"
    risk = Risk.READ
    description = (
        "Observe the local Mac before acting: check Accessibility and Screen Recording permissions, "
        "capture the screen, identify the frontmost application, or list its windows."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "screenshot", "frontmost", "windows"],
                "description": "Observation to perform",
            }
        },
        "required": ["action"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        action = str(args.get("action", "")).strip()
        try:
            if action == "status":
                return CapabilityResult(ok=True, output=json.dumps(computer_permission_status(), ensure_ascii=False))
            if action == "screenshot":
                path = _trace_path("screenshot")
                await _screenshot(path)
                return CapabilityResult(ok=True, output=f"screenshot:{path}")
            if action == "frontmost":
                output = await _osascript(
                    'tell application "System Events" to get name of first application process whose frontmost is true'
                )
                return CapabilityResult(ok=True, output=output)
            if action == "windows":
                output = await _osascript(
                    'tell application "System Events" to tell first application process whose frontmost is true '
                    'to get name of every window'
                )
                return CapabilityResult(ok=True, output=output or "(no windows)")
            return CapabilityResult(ok=False, error=f"unsupported observation action: {action}")
        except Exception as exc:
            return CapabilityResult(ok=False, error=str(exc))


class GUIControl:
    name = "gui.control"
    risk = Risk.DESTRUCTIVE
    description = (
        "Control the local Mac after observing it: click coordinates or a named UI element, type text, "
        "send a keyboard shortcut, or activate an application. Actions are captured before and after."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "double_click", "click_named", "type", "key", "open_app"],
                "description": "GUI action to execute",
            },
            "x": {"type": "number", "description": "Screen X coordinate"},
            "y": {"type": "number", "description": "Screen Y coordinate"},
            "text": {"type": "string", "description": "Text to type or UI element name"},
            "key": {"type": "string", "description": "Shortcut, for example command+c or enter"},
            "app_name": {"type": "string", "description": "Application name"},
        },
        "required": ["action"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        action = str(args.get("action", "")).strip()
        os.makedirs(_TRACE_DIR, exist_ok=True)
        before = _trace_path(f"before_{action}")
        after = _trace_path(f"after_{action}")
        try:
            status = computer_permission_status()
            if not status.get("accessibility"):
                return CapabilityResult(
                    ok=False,
                    error="macOS Accessibility permission is not enabled for Captain; open Settings > Privacy & Security > Accessibility",
                )
            if not status.get("screen_recording"):
                return CapabilityResult(
                    ok=False,
                    error="macOS Screen Recording permission is not enabled for Captain; open Settings > Privacy & Security > Screen Recording",
                )
            await _screenshot(before)
            if action in {"click", "double_click"}:
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
                count = 2 if action == "double_click" else 1
                for _ in range(count):
                    await _osascript(f'tell application "System Events" to click at {{{x}, {y}}}')
                    if count > 1:
                        await asyncio.sleep(0.08)
            elif action == "click_named":
                target = str(args.get("text", "")).strip()
                if not target:
                    return CapabilityResult(ok=False, error="click_named requires text")
                await _click_named(target)
            elif action == "type":
                await _paste_text(str(args.get("text", "")))
            elif action == "key":
                await _send_key(str(args.get("key", "")))
            elif action == "open_app":
                app = str(args.get("app_name", "")).strip()
                if not app:
                    return CapabilityResult(ok=False, error="open_app requires app_name")
                proc = await asyncio.create_subprocess_exec(
                    "open", "-a", app,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, err = await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode != 0:
                    raise RuntimeError(err.decode("utf-8", "replace").strip() or "application could not be opened")
            else:
                return CapabilityResult(ok=False, error=f"unsupported control action: {action}")
            await asyncio.sleep(0.25)
            await _screenshot(after)
            return CapabilityResult(
                ok=True,
                output=json.dumps({"action": action, "before": before, "after": after}, ensure_ascii=False),
            )
        except Exception as exc:
            return CapabilityResult(ok=False, error=str(exc))


def _trace_path(label: str) -> str:
    os.makedirs(_TRACE_DIR, exist_ok=True)
    return os.path.abspath(os.path.join(_TRACE_DIR, f"{int(time.time() * 1000)}_{label}.png"))


async def _screenshot(path: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "screencapture", "-x", "-t", "png", path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(proc.communicate(), timeout=10)
    if proc.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) == 0:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
        detail = err.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or "screen capture failed; grant Screen Recording permission to Captain")


async def _osascript(script: str) -> str:
    return await _osascript_args(script, [])


async def _osascript_args(script: str, args: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script, "--", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(err.decode("utf-8", "replace").strip() or "AppleScript failed")
    return out.decode("utf-8", "replace").strip()


async def _paste_text(text: str) -> None:
    script = """on run argv
set previousClipboard to the clipboard
set the clipboard to (item 1 of argv)
tell application "System Events" to keystroke "v" using {command down}
delay 0.15
set the clipboard to previousClipboard
end run"""
    await _osascript_args(script, [text])


async def _send_key(combo: str) -> None:
    parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
    if not parts:
        raise ValueError("key is required")
    key = parts[-1]
    modifier_map = {
        "command": "command down", "cmd": "command down", "shift": "shift down",
        "option": "option down", "alt": "option down", "ctrl": "control down", "control": "control down",
    }
    modifiers = [modifier_map[part] for part in parts[:-1] if part in modifier_map]
    using = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
    key_codes = {"enter": 36, "return": 36, "tab": 48, "escape": 53, "esc": 53,
                 "delete": 51, "backspace": 51, "left": 123, "right": 124,
                 "down": 125, "up": 126, "space": 49}
    if key in key_codes:
        script = f'tell application "System Events" to key code {key_codes[key]}{using}'
    else:
        script = f'on run argv\n tell application "System Events" to keystroke (item 1 of argv){using}\nend run'
    await _osascript_args(script, [] if key in key_codes else [key])


async def _click_named(target: str) -> None:
    script = """on run argv
set targetName to item 1 of argv
tell application "System Events"
  set frontProcess to first application process whose frontmost is true
  tell frontProcess
    if (count of windows) is 0 then error "frontmost application has no window"
    set candidates to entire contents of front window
    repeat with candidate in candidates
      try
        set candidateName to name of candidate as text
        set candidateDescription to description of candidate as text
        if candidateName is targetName or candidateDescription is targetName then
          perform action "AXPress" of candidate
          return
        end if
      end try
    end repeat
  end tell
end tell
error "UI element not found: " & targetName
end run"""
    await _osascript_args(script, [target])
