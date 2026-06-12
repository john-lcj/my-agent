"""组合根(composition root)—— 唯一知道"具体用谁"的地方。

运行:
    python main.py                # 默认用 MockLLM,无需任何 API key
    AGENT_PROVIDER=deepseek python main.py   # 用真实模型(需在 .env 配 key)
    my agent cli                    # 同上
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from config import Config, load_env
from core.status_bar import emit_status_event
from core.coordinator_stack import build_coordinator_stack
from core.types import Identity
from channels.cli import CLIChannel
from core.persona import load_persona
from memory.factory import build_longterm
from memory.session_store import SessionStore
from server.runtime_config import RuntimeConfigStore
from llm.model_registry import get_model


def _discover_skill_names() -> set[str]:
    from skills.paths import build_skill_registry
    reg = build_skill_registry()
    reg.discover()
    return {m.name for m in reg.available()}


def _skill_manifests():
    from skills.paths import build_skill_registry
    reg = build_skill_registry()
    reg.discover()
    return reg.available()


def build_agent_and_channel(model: Optional[str] = None, channel: Optional[CLIChannel] = None):
    persona = load_persona()
    longterm = build_longterm(Config.LOG_DIR)
    session_store = SessionStore(db_path=f"{Config.LOG_DIR}/sessions.db")
    runtime = RuntimeConfigStore(path=f"{Config.LOG_DIR}/runtime.json")
    model_id = model or runtime.get_model()

    if channel is None:
        channel = CLIChannel()

    coordinator, bundle = build_coordinator_stack(
        Identity(subject_id="local-user", agent_name="captain", channel="cli"),
        profile="cli",
        longterm=longterm,
        persona=persona,
        event_sink=channel.emit,
        trace_echo=False,
        model=model_id,
    )
    agent, ctx, rollback = bundle.agent, bundle.ctx, bundle.rollback
    channel.ctx = ctx
    ctx.bind_session(session_store, "cli-local")

    return agent, coordinator, channel, ctx, rollback, bundle, model_id, session_store, persona, longterm, runtime


def rebuild_stack(
    model_id: str,
    channel: CLIChannel,
    old_ctx,
    session_store,
    persona,
    longterm,
    runtime: RuntimeConfigStore,
):
    """切换模型时保留会话上下文。"""
    spec = get_model(model_id)
    runtime.save({"model": model_id, "provider": spec.provider})
    coordinator, bundle = build_coordinator_stack(
        Identity(subject_id="local-user", agent_name="captain", channel="cli"),
        profile="cli",
        longterm=longterm,
        persona=persona,
        event_sink=channel.emit,
        trace_echo=False,
        model=model_id,
    )
    new_ctx = bundle.ctx
    new_ctx.messages = list(old_ctx.messages)
    new_ctx.grants = set(old_ctx.grants)
    new_ctx.capability_grants = set(old_ctx.capability_grants)
    sid = old_ctx.session_id or "cli-local"
    new_ctx.bind_session(session_store, sid)
    channel.ctx = new_ctx
    return bundle.agent, coordinator, bundle, new_ctx, model_id


async def _invoke_skill_cli(skill_name: str, task: str, bundle, ctx, channel: CLIChannel) -> str:
    from agents.commands import parse_skill_args

    cap_name = f"skill.{skill_name}"
    cap = bundle.registry.get(cap_name)
    if cap is None:
        return f"未找到 skill `{skill_name}`。输入 /skills 查看列表。"

    args = parse_skill_args(skill_name, task)
    channel.print_skill_invoke(skill_name, args)
    result = await cap.invoke(args, ctx)
    if result.ok:
        text = result.output or "(无输出)"
        from channels.cli_style import print_agent_block
        print_agent_block(text, f"skill.{skill_name}")
        return text
    err = result.error or "执行失败"
    from channels.cli_style import print_err
    print_err(f"skill 错误: {err}")
    return err


def _collect_banner_meta() -> tuple[list[tuple[str, str]], list[tuple[str, str]], set[str]]:
    experts: list[tuple[str, str]] = []
    expert_names: set[str] = set()
    try:
        from agents.spec import load_specs_from_roster
        for s in load_specs_from_roster("agents/roster"):
            expert_names.add(s.name)
            experts.append((s.name, s.role or s.name))
    except Exception:
        pass

    skills: list[tuple[str, str]] = []
    for m in _skill_manifests():
        skills.append((m.name, m.description or m.name))

    return experts, skills, expert_names


async def main() -> None:
    load_env()

    experts_meta, skills_meta, expert_names = _collect_banner_meta()
    skill_names = {s[0] for s in skills_meta}

    from channels.cli_banner import prelude_entrance

    showed_prelude = prelude_entrance()

    (
        agent, coordinator, channel, ctx, rollback, bundle, model_id,
        session_store, persona, longterm, runtime,
    ) = build_agent_and_channel()

    try:
        from server.commands_api import list_slash_commands
        from skills.paths import resolve_skills_dirs
        roster = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents", "roster")
        channel.slash_commands = list_slash_commands(roster, resolve_skills_dirs())
    except Exception:
        channel.slash_commands = []

    from channels.cli_banner import show_captain_banner

    tagline = (persona.tagline if persona else "") or "有分寸感的总指挥助理"
    show_captain_banner(
        model_id=model_id,
        tagline=tagline,
        project_root=os.path.dirname(os.path.abspath(__file__)),
        experts=experts_meta,
        skills=skills_meta,
        animate=not showed_prelude,
        clear=not showed_prelude,
    )

    session_started_at = time.time()
    channel.session_started_at = session_started_at

    def _push_status(last_task_seconds: Optional[float] = None) -> None:
        emit_status_event(
            channel, agent, ctx, model_id, session_started_at, last_task_seconds,
        )

    _push_status()

    from agents.commands import (
        format_models_help,
        format_skills_help,
        parse_slash_command,
    )

    while True:
        user_text = await channel.receive()
        if user_text is None:
            print("\n再见。")
            return
        if not user_text:
            continue

        if user_text.strip() == "/rollback":
            if agent.last_trace_id and rollback:
                from channels.cli_style import print_system
                for note in rollback.rollback(agent.last_trace_id):
                    print_system(f"↩ {note}")
            else:
                from channels.cli_style import print_system
                print_system("(还没有可回滚的任务)")
            continue

        cmd = parse_slash_command(user_text, expert_names, skill_names)

        if cmd.kind == "list_models":
            from channels.cli_style import print_system
            print_system(format_models_help(model_id))
            continue

        if cmd.kind == "set_model":
            agent, coordinator, bundle, ctx, model_id = rebuild_stack(
                cmd.target, channel, ctx, session_store, persona, longterm, runtime,
            )
            rollback = bundle.rollback
            channel.print_model_switch(model_id)
            _push_status(0)
            continue

        if cmd.kind == "list_skills":
            from channels.cli_style import print_system
            print_system(format_skills_help(_skill_manifests()))
            continue

        if cmd.kind == "invoke_skill":
            t0 = time.time()
            await _invoke_skill_cli(cmd.target, cmd.task, bundle, ctx, channel)
            _push_status(time.time() - t0)
            continue

        t0 = time.time()
        try:
            await coordinator.run(user_text, ctx, channel.confirm)
        except Exception as e:
            from llm.errors import format_llm_error
            from channels.cli_style import print_err
            print_err(format_llm_error(e))
        finally:
            _push_status(time.time() - t0)


def cli() -> None:
    """控制台入口(console_scripts)。

    打包安装后通过 `myagent` 调用。把工作目录切到项目根,使 policy.yaml /
    skills/ / frontend/ 等相对路径正常解析(editable 安装下即仓库目录)。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    os.environ.setdefault("AGENT_PROJECT_ROOT", root)
    try:
        os.chdir(root)
    except OSError:
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见。")


if __name__ == "__main__":
    cli()
