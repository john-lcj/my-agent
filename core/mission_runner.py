"""Mission 执行引擎 —— 单 agent 顺序推进一个 mission 的子任务。

职责:规划(把目标拆成子任务)→ 顺序执行每个子任务 → 推进状态机 → 完成/失败。
"如何执行一个子任务"通过注入的 `execute(prompt)->str` 接缝完成:
  · 测试里传一个假的 execute(确定性、离线);
  · 服务端传"建无人值守 agent 跑这段文字"的真实实现。
这样引擎只管编排和状态机,不依赖 LLM/网络,可单测。

MVP 范围:规划 + 顺序执行到完成/失败。Blocked/邮件中断恢复在下一块接入。
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

from core.mission import MissionStatus

ExecuteFn = Callable[[str], Awaitable[str]]
EmitFn = Optional[Callable[[str, dict], None]]
NotifyFn = Optional[Callable[[dict, str], None]]   # (mission, reason) → 通知用户(如发邮件)

_MAX_TASKS = 8

# 卡住协议:让子任务在"缺资料/需授权/需决策、无法继续"时,用固定前缀回报,而不是瞎编。
_BLOCK_PROTOCOL = (
    "\n\n【重要】如果缺少必要的资料/授权/付款/决策,导致你无法真正完成这一步,"
    "不要编造或假装完成——只回一行,以 `NEED_INPUT:` 开头,后面简短说明缺什么、要主人提供什么。"
    "例如:NEED_INPUT: 缺德国营业执照扫描件,请上传后我继续。"
)
_NEED = "NEED_INPUT:"


def _need_input(result: str) -> str:
    """若子任务回报卡住,返回卡住原因;否则空串。"""
    s = (result or "").strip()
    if s.startswith(_NEED):
        return s[len(_NEED):].strip() or "需要你补充信息"
    return ""


def _context_preamble(mission: dict) -> str:
    notes = [c.get("note", "") for c in (mission.get("context") or []) if c.get("note")]
    if not notes:
        return ""
    return "主人已补充的资料/决策(执行时请利用):\n" + "\n".join(f"- {n}" for n in notes) + "\n\n"


def _plan_prompt(goal: str) -> str:
    return (
        "你是项目执行助手。把下面这个目标拆成 2~6 个**可顺序执行**的子任务。\n"
        "要求:每行一个子任务,动词开头,具体可执行;不要编号、不要解释、不要空行。\n\n"
        f"目标:{goal}"
    )


def _parse_tasks(text: str) -> list[str]:
    """把模型规划输出解析成子任务列表(去编号/项目符号/空行,限量)。"""
    out: list[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^\s*(\d+[.)、]|[-*•·]|第[一二三四五六七八九十]+步)[:：]?\s*", "", s).strip()
        if s:
            out.append(s)
        if len(out) >= _MAX_TASKS:
            break
    return out


async def plan_mission(store, mid: str, execute: ExecuteFn) -> list[dict]:
    """若 mission 还没有子任务,让模型把目标拆解并落库。返回子任务列表。"""
    m = store.get(mid)
    if m is None:
        raise KeyError(mid)
    if m["tasks"]:
        return m["tasks"]
    store.set_status(mid, MissionStatus.PLANNING.value)
    plan_text = await execute(_plan_prompt(m["goal"]))
    tasks = _parse_tasks(plan_text) or [m["goal"]]   # 解析不出来就整体当一个子任务
    return store.set_tasks(mid, tasks)["tasks"]


async def run_mission(store, mid: str, execute: ExecuteFn,
                      emit: EmitFn = None, notify: NotifyFn = None) -> dict:
    """完整推进一个 mission:规划 → 顺序执行子任务 → 完成/失败/卡住。返回最终 mission。

    子任务回报 `NEED_INPUT:` 时 → 置 BLOCKED + 调 notify(发邮件找主人)+ 暂停(任务保留 pending)。
    主人补料后用 resume_mission 恢复:补充信息进 context,从卡住的任务继续。
    """
    def _emit(kind: str, payload: dict) -> None:
        if emit:
            try:
                emit(kind, {"mission_id": mid, **payload})
            except Exception:
                pass

    m = store.get(mid)
    if m is None:
        raise KeyError(mid)
    if m["status"] in ("completed", "cancelled"):
        return m

    _emit("mission.started", {"goal": m["goal"]})
    # 1) 规划(先进入 planning 态,再拆解;预置了子任务也要先过 planning,保证状态机合法)
    try:
        if m["status"] == MissionStatus.CREATED.value:
            store.set_status(mid, MissionStatus.PLANNING.value)
        await plan_mission(store, mid, execute)
    except Exception as e:
        store.set_status(mid, MissionStatus.FAILED.value, reason=f"规划失败:{e}")
        _emit("mission.failed", {"stage": "planning", "error": str(e)})
        return store.get(mid)

    # 2) 顺序执行
    store.set_status(mid, MissionStatus.EXECUTING.value)
    _emit("mission.planned", {"tasks": [t["text"] for t in store.get(mid)["tasks"]]})

    guard = 0
    while True:
        guard += 1
        if guard > _MAX_TASKS + 2:        # 防御:别无限循环
            break
        # 取消可被外部置位 → 尊重它
        cur = store.get(mid)
        if cur["status"] == "cancelled":
            return cur
        t = store.next_task(mid)
        if t is None:
            break
        _emit("task.started", {"task_id": t["id"], "text": t["text"]})
        try:
            prompt = _context_preamble(cur) + t["text"] + _BLOCK_PROTOCOL
            result = await execute(prompt)
            reason = _need_input(result)
            if reason:   # 卡住:置 BLOCKED + 通知,任务保留 pending,等恢复
                store.set_status(mid, MissionStatus.BLOCKED.value, reason=reason)
                store.add_notification(mid, cur.get("attention_level", 2), reason)
                if notify:
                    try:
                        notify(store.get(mid), reason)
                    except Exception:
                        pass
                _emit("mission.blocked", {"task_id": t["id"], "reason": reason})
                return store.get(mid)
            store.update_task(mid, t["id"], status="done", result=(result or "")[:4000])
            _emit("task.done", {"task_id": t["id"]})
        except Exception as e:
            store.update_task(mid, t["id"], status="failed", result=str(e))
            store.set_status(mid, MissionStatus.FAILED.value, reason=f"子任务失败:{t['text']}")
            _emit("mission.failed", {"stage": "executing", "task_id": t["id"], "error": str(e)})
            return store.get(mid)

    # 3) 完成
    store.set_status(mid, MissionStatus.COMPLETED.value)
    _emit("mission.completed", {})
    return store.get(mid)


async def resume_mission(store, mid: str, execute: ExecuteFn, info: str = "",
                         emit: EmitFn = None, notify: NotifyFn = None) -> dict:
    """主人补料后恢复一个卡住的 mission:补充信息进 context → 置 EXECUTING → 从卡住的任务继续。"""
    m = store.get(mid)
    if m is None:
        raise KeyError(mid)
    if m["status"] not in (MissionStatus.BLOCKED.value, MissionStatus.WAITING_USER.value):
        return m   # 只恢复卡住/等待中的
    if (info or "").strip():
        store.add_context(mid, info)
    store.set_status(mid, MissionStatus.EXECUTING.value)
    return await run_mission(store, mid, execute, emit=emit, notify=notify)
