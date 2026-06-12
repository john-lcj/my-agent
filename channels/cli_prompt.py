"""CLI 交互式输入 —— 状态栏嵌入 prompt_toolkit 消息区(❯ 上方),输入不跳动。"""
from __future__ import annotations

import sys
from typing import Any, Optional

_PROMPT_SESSION = None
_STYLE = None


def _can_use_interactive() -> bool:
    try:
        import termios

        if not sys.stdin.isatty():
            return False
        termios.tcgetattr(sys.stdin.fileno())
        return True
    except Exception:
        return False


def _make_slash_completer(commands: list[dict[str, Any]]):
    from prompt_toolkit.completion import Completer, Completion

    sorted_cmds = sorted(
        commands,
        key=lambda c: (c.get("group") or "", c.get("cmd") or ""),
    )

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):  # noqa: ANN001
            line = document.text_before_cursor
            if not line.startswith("/"):
                return

            low = line.lower()
            for item in sorted_cmds:
                cmd = (item.get("cmd") or "").strip()
                if not cmd or not cmd.lower().startswith(low):
                    continue
                label = item.get("label") or ""
                group = item.get("group") or ""
                meta = f"{group} · {label}" if group and label else (label or group)
                yield Completion(
                    cmd,
                    start_position=-len(line),
                    display=cmd,
                    display_meta=meta,
                )

    return SlashCommandCompleter()


def _make_slash_ghost_suggest(commands: list[dict[str, Any]]):
    from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion

    cmds = sorted({(c.get("cmd") or "").strip() for c in commands if c.get("cmd")})

    class SlashGhostSuggest(AutoSuggest):
        def get_suggestion(self, buffer, document):  # noqa: ANN001
            text = document.text
            if not text.startswith("/"):
                return None
            low = text.lower()
            for cmd in cmds:
                if cmd.lower().startswith(low) and cmd.lower() != low:
                    return Suggestion(cmd[len(text):])
            return None

    return SlashGhostSuggest()


def _prompt_style():
    global _STYLE
    if _STYLE is None:
        from prompt_toolkit.styles import Style

        _STYLE = Style.from_dict({
            "status": "ansibrightblack",
            "sep": "ansibrightblack",
        })
    return _STYLE


def _prompt_session():
    global _PROMPT_SESSION
    if _PROMPT_SESSION is None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings

        hist_path = __import__("os").path.expanduser("~/.captain/cli_history")
        __import__("os").makedirs(__import__("os").path.dirname(hist_path), exist_ok=True)

        bindings = KeyBindings()

        @bindings.add("c-j")
        def _newline(event):  # noqa: ANN001
            event.current_buffer.insert_text("\n")

        @bindings.add("escape", "enter")
        def _newline_alt(event):  # noqa: ANN001
            event.current_buffer.insert_text("\n")

        _PROMPT_SESSION = PromptSession(
            history=FileHistory(hist_path),
            enable_open_in_editor=False,
            multiline=False,
            key_bindings=bindings,
            style=_prompt_style(),
        )
    return _PROMPT_SESSION


def _make_prompt_message(
    status_payload: dict | None,
    session_started_at: float | None,
):
    from prompt_toolkit.formatted_text import FormattedText

    from channels.cli_style import format_live_status, prompt_prefix, status_separator

    def _message() -> FormattedText:
        line = format_live_status(status_payload, session_started_at)
        parts: list[tuple[str, str]] = []
        if line:
            parts.append(("class:status", line + "\n"))
            w = min(__import__("shutil").get_terminal_size((80, 24)).columns, 72)
            parts.append(("class:sep", "─" * w + "\n"))
        parts.append(("", prompt_prefix()))
        return FormattedText(parts)

    return _message


def read_line_interactive(
    *,
    slash_commands: list[dict],
    status_payload: dict | None = None,
    session_started_at: float | None = None,
    use_menu: bool = True,
) -> Optional[str]:
    if not _can_use_interactive():
        return _readline_fallback(slash_commands, status_payload, session_started_at)

    try:
        from prompt_toolkit.shortcuts import CompleteStyle

        session = _prompt_session()
        completer = (
            _make_slash_completer(slash_commands)
            if use_menu and slash_commands
            else None
        )
        auto_suggest = (
            _make_slash_ghost_suggest(slash_commands)
            if use_menu and slash_commands
            else None
        )

        text = session.prompt(
            _make_prompt_message(status_payload, session_started_at),
            completer=completer,
            auto_suggest=auto_suggest,
            complete_while_typing=bool(completer),
            complete_style=CompleteStyle.COLUMN,
            refresh_interval=1.0,
        )
        return (text or "").strip()
    except (EOFError, KeyboardInterrupt):
        raise
    except Exception:
        return _readline_fallback(slash_commands, status_payload, session_started_at)


def _readline_fallback(
    slash_commands: list[dict],
    status_payload: dict | None = None,
    session_started_at: float | None = None,
) -> Optional[str]:
    from channels.cli_style import format_live_status, prompt_prefix, status_separator

    line = format_live_status(status_payload, session_started_at)
    if line:
        import re
        plain = re.sub(r"\033\[[0-9;]*m", "", line)
        print(plain)
        print(status_separator())
    try:
        import readline

        cmds = [c.get("cmd", "") for c in slash_commands if c.get("cmd")]

        def completer(text, state):
            opts = [c for c in cmds if c.startswith(text)]
            return opts[state] if state < len(opts) else None

        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
        return input(prompt_prefix()).strip()
    except Exception:
        return input(prompt_prefix()).strip()
