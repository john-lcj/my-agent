"""电脑 GUI 控制 —— macOS 原生实现(screencapture + osascript),零额外依赖。

安全设计:
- 风险固定为 DESTRUCTIVE,每次调用都会过治理层确认。
- 每个动作执行前后自动截图存证(存入 logs/gui_trace/),可供审计/回放。
- 高危动作(type/key)要求调用者在 intent 里说明原因。

支持的 action:
  screenshot  截取当前屏幕,存入 logs/gui_trace/ 并返回路径。
  click       在指定坐标点击(需 x, y)。
  move        移动鼠标到指定坐标(不点击)。
  type        在当前焦点处键入文本(需 text)。
  key         发送一个按键组合,如 "command+c"(需 key)。
  open_app    通过 osascript 打开一个应用(需 app_name)。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from core.types import CapabilityResult, Risk

_TRACE_DIR = os.path.join("logs", "gui_trace")


class GUIControl:
    name = "gui.control"
    risk = Risk.DESTRUCTIVE
    description = (
        "控制电脑图形界面:截图/移动鼠标/点击/键入/发送按键/打开应用。"
        "每个动作前后自动截图留证。高危能力,默认需确认。"
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["screenshot", "click", "move", "type", "key", "open_app"],
                "description": "要执行的 GUI 动作",
            },
            "x": {"type": "number", "description": "屏幕 X 坐标(click/move)"},
            "y": {"type": "number", "description": "屏幕 Y 坐标(click/move)"},
            "text": {"type": "string", "description": "要键入的文本(type)"},
            "key": {"type": "string", "description": "按键组合,如 'command+c'(key)"},
            "app_name": {"type": "string", "description": "应用名称(open_app)"},
        },
        "required": ["action"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        action = str(args.get("action", "")).strip()
        os.makedirs(_TRACE_DIR, exist_ok=True)
        ts = int(time.time() * 1000)

        # 动作前截图(screenshot 动作本身跳过前截图)
        if action != "screenshot":
            before = os.path.join(_TRACE_DIR, f"{ts}_before_{action}.png")
            await _screenshot(before)

        try:
            if action == "screenshot":
                path = os.path.join(_TRACE_DIR, f"{ts}_screenshot.png")
                await _screenshot(path)
                return CapabilityResult(ok=True, output=f"截图已保存:{path}")

            elif action == "click":
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
                await _osascript(f'tell application "System Events" to click at {{{x}, {y}}}')

            elif action == "move":
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
                await _osascript(
                    f'tell application "System Events" '
                    f'to set the position of the mouse to {{{x}, {y}}}'
                )

            elif action == "type":
                text = str(args.get("text", ""))
                escaped = text.replace('"', '\\"')
                await _osascript(
                    f'tell application "System Events" to keystroke "{escaped}"'
                )

            elif action == "key":
                combo = str(args.get("key", ""))
                parts = [p.strip() for p in combo.split("+")]
                key = parts[-1]
                mods = [_MOD_MAP.get(m, m) for m in parts[:-1]]
                mod_str = (", ".join(f"{{{m}}}" for m in mods)) if mods else ""
                using_clause = f" using {{{', '.join(f'{m} down' for m in mods)}}}" if mods else ""
                await _osascript(
                    f'tell application "System Events" to keystroke "{key}"{using_clause}'
                )

            elif action == "open_app":
                app = str(args.get("app_name", ""))
                await _osascript(f'tell application "{app}" to activate')

            else:
                return CapabilityResult(ok=False, error=f"不支持的 action: {action}")

        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))

        # 动作后截图
        after = os.path.join(_TRACE_DIR, f"{ts}_after_{action}.png")
        await _screenshot(after)

        return CapabilityResult(ok=True, output=f"动作 [{action}] 已执行,截图存证:{after}")


# ── 辅助 ──────────────────────────────────────────────────────────────────────

_MOD_MAP = {
    "command": "command key",
    "cmd": "command key",
    "shift": "shift key",
    "option": "option key",
    "alt": "option key",
    "ctrl": "control key",
    "control": "control key",
}


async def _screenshot(path: str) -> None:
    """用系统 screencapture 截图(无需任何第三方库)。"""
    proc = await asyncio.create_subprocess_exec(
        "screencapture", "-x", "-t", "png", path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(proc.communicate(), timeout=10)


async def _osascript(script: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(proc.communicate(), timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(err.decode("utf-8", "replace").strip())
