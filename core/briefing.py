"""每日简报 —— 统一 scheduler 任务与主动 digest 为单一 daily_briefing。"""
from __future__ import annotations

import json
import os
import re
import time

BRIEFING_TASK_NAME = "每日简报"

_REMOVED_CHANNELS = {"qq", "wechat", "slack", "telegram", "onebot"}

MONITOR_DIGEST_QUEUE = "monitor_digest_queue.json"


def _journal_plain_summary(log_dir: str, limit: int = 2) -> str:
    """协作日志纯文本摘要(去 Markdown,供邮件/简报用)。"""
    path = os.path.join(log_dir, "journal.md")
    if not os.path.isfile(path):
        return "暂无近期协作记录。"
    try:
        from memory.journal import Journal
        chunks = Journal(path=path).recent(limit)
    except Exception:
        return "暂无近期协作记录。"
    if not chunks:
        return "暂无近期协作记录。"
    lines: list[str] = []
    for chunk in chunks:
        text = chunk.strip()
        text = re.sub(r"^##\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text:
            lines.append(text.strip())
    return "\n\n".join(lines) if lines else "暂无近期协作记录。"


def _journal_recent_summary(log_dir: str, limit: int = 2) -> str:
    return _journal_plain_summary(log_dir, limit)


def _mission_progress_lines(mission_store) -> tuple[list[str], list[str]]:
    """返回 (进行中 mission 行, 需决策 BLOCKED 行)。"""
    executing, blocked = [], []
    if mission_store is None:
        return executing, blocked
    try:
        for m in mission_store.list():
            st = m.get("status", "")
            goal = (m.get("goal") or "")[:50]
            tasks = m.get("tasks") or []
            done = sum(1 for t in tasks if t.get("status") == "done")
            total = len(tasks)
            if st == "executing":
                cur = next((t.get("text", "")[:40] for t in tasks if t.get("status") == "pending"), "")
                prog = f"{done}/{total}" if total else "规划中"
                line = f"· {goal}（进度 {prog}）"
                if cur:
                    line += f"，当前：{cur}"
                executing.append(line)
            elif st in ("blocked", "waiting_user"):
                reason = (m.get("blocked_reason") or "待补充")[:80]
                blocked.append(f"· {goal}：{reason}（Mission #{m.get('id', '')[:8]}）")
    except Exception:
        pass
    return executing, blocked


def load_monitor_digest_queue(log_dir: str) -> list[dict]:
    path = os.path.join(log_dir, MONITOR_DIGEST_QUEUE)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def enqueue_monitor_digest(log_dir: str, name: str, source: str, message: str) -> None:
    path = os.path.join(log_dir, MONITOR_DIGEST_QUEUE)
    os.makedirs(log_dir, exist_ok=True)
    rows = load_monitor_digest_queue(log_dir)
    rows.append({
        "ts": time.time(),
        "name": name,
        "source": source,
        "message": message[:500],
    })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows[-50:], f, ensure_ascii=False, indent=2)


def drain_monitor_digest_queue(log_dir: str) -> list[dict]:
    rows = load_monitor_digest_queue(log_dir)
    path = os.path.join(log_dir, MONITOR_DIGEST_QUEUE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
    except Exception:
        pass
    return rows


def build_daily_briefing_context(*, log_dir: str, longterm=None, mission_store=None) -> str:
    parts = [f"【当前时间】{time.strftime('%Y-%m-%d %H:%M')}"]

    parts.append("【昨日完成 / 近期协作】\n" + _journal_plain_summary(log_dir, 2))

    try:
        from memory.goals_store import GoalsStore
        goals = GoalsStore(path=os.path.join(log_dir, "goals.json")).active_texts()
    except Exception:
        goals = []
    goal_lines = "\n".join(f"· {g}" for g in goals) if goals else "· (暂无登记目标)"
    exec_lines, blocked_lines = _mission_progress_lines(mission_store)
    todo_parts = [f"长期目标:\n{goal_lines}"]
    if exec_lines:
        todo_parts.append("进行中的 Mission:\n" + "\n".join(exec_lines))
    parts.append("【今日待办】\n" + "\n\n".join(todo_parts))

    decision_parts = []
    if blocked_lines:
        decision_parts.append("BLOCKED Mission（需你决策/补料）:\n" + "\n".join(blocked_lines))
    digest = load_monitor_digest_queue(log_dir)
    if digest:
        md = "\n".join(
            f"· 监控「{d.get('name')}」: {d.get('message', '')[:120]}"
            for d in digest[-10:]
        )
        decision_parts.append("监控关注（normal 级，攒进简报）:\n" + md)
    if decision_parts:
        parts.append("【需决策 / 需关注】\n" + "\n\n".join(decision_parts))
    else:
        parts.append("【需决策 / 需关注】\n(暂无)")

    try:
        from memory.task_rating import weekly_summary
        ws = weekly_summary(log_dir, days=7.0)
        if ws.get("count", 0) >= 3 and ws.get("avg", 5) < 3.5:
            parts.append(
                f"【近 7 天任务自评】平均 {ws['avg']}/5（{ws['count']} 次），"
                "建议关注低分任务类型并固化经验。"
            )
    except Exception:
        pass

    return "\n\n".join(parts)


def format_daily_briefing_email(*, log_dir: str, mission_store=None) -> str:
    """确定性简报Body text(纯文本,只引用真实数据,不经 LLM 编造)。"""
    now = time.strftime("%Y-%m-%d %H:%M")
    yesterday = _journal_plain_summary(log_dir, 2)

    try:
        from memory.goals_store import GoalsStore
        goals = GoalsStore(path=os.path.join(log_dir, "goals.json")).active_texts()
    except Exception:
        goals = []
    exec_lines, blocked_lines = _mission_progress_lines(mission_store)
    digest = load_monitor_digest_queue(log_dir)

    lines = [
        f"Captain 每日简报 · {now}",
        "",
        "一、昨日完成",
        yesterday,
        "",
        "二、今日待办",
    ]
    if goals:
        lines.append("长期目标：")
        lines.extend(f"  · {g}" for g in goals)
    else:
        lines.append("长期目标：暂无登记。")
    if exec_lines:
        lines.append("")
        lines.append("进行中的 Mission：")
        lines.extend(f"  {ln.lstrip('· ')}" if ln.startswith("·") else f"  {ln}" for ln in exec_lines)
    elif not goals:
        lines.append("  暂无进行中的 Mission。")

    lines.extend(["", "三、需你决策"])
    decision_items: list[str] = []
    decision_items.extend(blocked_lines)
    for d in digest[-10:]:
        decision_items.append(f"· 监控「{d.get('name')}」: {d.get('message', '')[:120]}")
    if decision_items:
        lines.extend(decision_items)
    else:
        lines.append("暂无。")

    try:
        from memory.task_rating import weekly_summary
        ws = weekly_summary(log_dir, days=7.0)
        if ws.get("count", 0) >= 3 and ws.get("avg", 5) < 3.5:
            lines.extend([
                "",
                f"附：近 7 天任务自评均分 {ws['avg']}/5（{ws['count']} 次），可关注低分类型。",
            ])
    except Exception:
        pass

    lines.extend(["", "—— Captain"])
    drain_monitor_digest_queue(log_dir)
    return "\n".join(lines)


DAILY_BRIEFING_PROMPT = """(已废弃 —— 简报改由 format_daily_briefing_email 确定性生成,见 core/briefing.py)"""

# 向后兼容旧名
BRIEFING_PROMPT = DAILY_BRIEFING_PROMPT


def ensure_briefing_task(store, *, at_hhmm: str, channel: str, to: str = "") -> bool:
    for t in store.list():
        if t.name == BRIEFING_TASK_NAME:
            if getattr(t, "deliver", "") in _REMOVED_CHANNELS:
                t.deliver = "email"
                t.deliver_to = ""
            if at_hhmm and getattr(t, "at_hhmm", "") != at_hhmm:
                t.at_hhmm = at_hhmm
                t.next_run = t.compute_next_run()
            store.save(t)
            return False
    if not channel or channel == "none":
        deliver = "none"
    else:
        deliver = channel
    store.create(
        name=BRIEFING_TASK_NAME,
        prompt=DAILY_BRIEFING_PROMPT,
        schedule_type="daily",
        at_hhmm=at_hhmm or "08:00",
        deliver=deliver,
        deliver_to=to,
        task_type="briefing",
    )
    return True


def resolve_briefing_prompt(task_prompt: str, *, log_dir: str, longterm=None, mission_store=None) -> str:
    """向后兼容:返回结构化 context(预览/调试),正式发送用 format_daily_briefing_email。"""
    return build_daily_briefing_context(
        log_dir=log_dir, longterm=longterm, mission_store=mission_store,
    )
