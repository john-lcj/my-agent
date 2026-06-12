"""命令行渠道 —— Hermes 风格流式输出、工具 feed、状态栏。"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

from channels.cli_style import (
    agent_color_enabled,
    agent_frame,
    format_cli_status,
    format_cli_text,
    print_agent_block,
    print_err,
    print_ok,
    print_system,
    sanitize_stream_token,
    write_agent_body,
    _box,
    _dim,
)
from core.types import CapabilityCall, Decision, Event, EventType, Identity


def print_tool_activity(name: str, args: dict | None = None, *, ok: bool | None = None) -> None:
    a = args or {}
    icon = next((i for p, i in (("skill.", "🔧"), ("fs.", "📄"), ("shell.", "💻"), ("web.", "🔍"), ("coordinator.", "👤"), ("memory.", "🧠")) if name.startswith(p)), "⚡")
    prev = (f"{a.get('agent', '?')} · {(a.get('task') or '')[:60]}" if name == "coordinator.invoke" else f"dispatch ({len(a.get('assignments') or [])} 专家)" if name == "coordinator.dispatch"
            else name[6:] if name.startswith("skill.") else str(a.get("path") or "")[:80] if name in ("fs.read", "fs.write")
            else str(a.get("command") or "")[:80] if name == "shell.run" else str(a.get("query") or a.get("q") or "")[:60] if name == "web.search" else name)
    line = f"  ┊ {icon} {prev}{' ✓' if ok is True else ' ✗' if ok is False else ''}"
    print(_dim(line) if agent_color_enabled() else line)


class AgentStreamBox:
    def __init__(self, source: str = "Captain") -> None:
        self.label, self._buf, self._open, self.prefix, self.w, self.inner = source, "", False, "", 0, 0

    def start(self) -> None:
        if self._open: return
        ind, self.w, self.inner = _box(); self.prefix = " " * ind
        sys.stdout.write(agent_frame(self.prefix, self.w, self.label)); self._open = True

    def write(self, token: str) -> None:
        t = sanitize_stream_token(token)
        if t and not self._open: self.start()
        if t: self._buf += t

    def finish(self, *, text: str | None = None) -> None:
        final = (text if text is not None else self._buf).strip()
        if not self._open and not final: return
        if not self._open: self.start()
        if final: write_agent_body(format_cli_text(final), self.prefix, self.inner)
        sys.stdout.write(agent_frame(self.prefix, self.w, self.label, True)); sys.stdout.flush()
        self._open, self._buf = False, ""


class CLIChannel:
    name = "cli"

    def __init__(self, ctx=None, *, concise_output: bool = True) -> None:
        self.ctx = ctx
        self._stream_box: AgentStreamBox | None = None
        self.status_line = ""
        self.status_payload: dict = {}
        self.session_started_at: float | None = None
        self.slash_commands: list[dict] = []
        self.concise_output = concise_output

    async def receive(self) -> Optional[str]:
        from channels.cli_prompt import read_line_interactive
        loop = asyncio.get_event_loop()
        try:
            line = await loop.run_in_executor(
                None,
                lambda: read_line_interactive(
                    slash_commands=self.slash_commands,
                    status_payload=self.status_payload,
                    session_started_at=self.session_started_at,
                ),
            )
        except (EOFError, KeyboardInterrupt):
            return None
        if line is None:
            return None
        line = line.strip()
        if line.lower() in {"exit", "quit", "退出", ":q"}:
            return None
        return line

    def emit(self, event: Event) -> None:
        et = event.type
        payload = event.payload or {}

        if et == EventType.ASSISTANT_TOKEN:
            token = payload.get("token", "")
            if not token:
                return
            source = payload.get("source") or "Captain"
            if self._stream_box is None:
                self._stream_box = AgentStreamBox(source)
            self._stream_box.write(token)
            return

        if et == EventType.ASSISTANT_MESSAGE:
            text = payload.get("text", "")
            source = (
                payload.get("expert_role")
                or payload.get("source")
                or "Captain"
            )
            if source in ("coordinator", "system"):
                source = "Captain"
            if self._stream_box is not None:
                self._stream_box.finish(text=text or None)
                self._stream_box = None
            elif text:
                print_agent_block(text, source)
            return

        if et == EventType.CAPABILITY_CALL:
            self._emit_capability_call(payload)
            return

        if et == EventType.CAPABILITY_RESULT:
            if self.concise_output:
                if not payload.get("ok"):
                    err = (payload.get("error") or "工具执行失败")[:160]
                    print_err(err)
                return
            ok = payload.get("ok")
            out = payload.get("output") or payload.get("error") or ""
            if out:
                preview = out if len(out) <= 200 else out[:200] + "…"
                print_system(preview if ok else f"失败: {preview}")
            return

        if et == EventType.STATUS_BAR:
            self.status_payload = dict(payload)
            self.status_line = format_cli_status(payload)
            return

        if et == EventType.ERROR:
            if self._stream_box is not None:
                self._stream_box.finish()
                self._stream_box = None
            print_err(str(payload.get("message") or "未知错误"))

    def _emit_capability_call(self, payload: dict) -> None:
        name = payload.get("name", "")
        args = payload.get("args") or {}
        print_tool_activity(name, args)

    def print_skill_invoke(self, skill_name: str, args: dict) -> None:
        print_tool_activity(f"skill.{skill_name}", args or {})

    def print_expert_invoke(self, agent_name: str, task: str) -> None:
        print_tool_activity("coordinator.invoke", {"agent": agent_name, "task": task})

    def print_model_switch(self, model_id: str) -> None:
        print_ok(f"已切换模型 → {model_id}")

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        if self._stream_box is not None:
            self._stream_box.finish()
            self._stream_box = None
        prompt = (
            f"\n确认 {call.name}"
            + (f" · {reason}" if reason else "")
            + " [y/n/a] ❯ "
        )
        ans = (await asyncio.get_event_loop().run_in_executor(None, input, prompt)).strip().lower()
        if ans == "a":
            path = call.args.get("path")
            if path and self.ctx is not None and hasattr(self.ctx, "grant"):
                self.ctx.grant(path)
            return True
        return ans in {"y", "yes", "是"}

    def identity(self) -> Identity:
        return Identity(subject_id="local-user", agent_name="captain", channel="cli")
