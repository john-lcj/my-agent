"""协作日志(伙伴记忆)—— 让 agent 成为"记得我们一起走到哪了"的长期伙伴。

现有长期记忆(事实/偏好/向量 RAG)解决"记得住零散的事";本模块补的是**连续感**:
每次会话结束,把"这次做了什么、定了什么、下一步是什么"沉淀成一条带时间戳的日志;
下次开场,把最近几条作为"上次到哪了"注入,让 agent 接得上,而不是每次从零开始。

刻意做成**人类可读的 markdown 文件**(logs/journal.md):你能直接翻、能手改,
agent 也读它 —— 记忆对你我都是透明、可控的,而不是黑箱。
"""
from __future__ import annotations

import json
import os
import re
import time


_SEP = "\n\n---\n\n"
_DIALOGUE_TURNS = 24

_CONSOLIDATE_PROMPT = """你在为一段协作会话写一条简短的"协作日志",供下次开场快速接续。
基于以下对话,提炼这次实际发生了什么。只写真实发生的,别编造。

对话:
{dialogue}

严格只输出 JSON(不要其他内容):
{{
  "summary": "一句话:这次主要做成/推进了什么(没有实质进展就如实写'主要是讨论/未落地')",
  "decisions": ["拍板的决定", "..."],
  "next_steps": ["明确的下一步", "..."]
}}"""


class Journal:
    def __init__(self, path: str = "logs/journal.md") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def append(self, summary: str, decisions: list[str] | None = None,
               next_steps: list[str] | None = None, when: float | None = None) -> None:
        """追加一条协作日志条目。summary 必填,decisions/next_steps 可选。"""
        summary = (summary or "").strip()
        if not summary:
            return
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(when or time.time()))
        lines = [f"## {ts}", "", f"**做了**:{summary}"]
        if decisions:
            lines.append("**决定**:" + "；".join(d.strip() for d in decisions if d.strip()))
        if next_steps:
            lines.append("**下一步**:" + "；".join(s.strip() for s in next_steps if s.strip()))
        entry = "\n".join(lines)
        existing = self._read()
        with open(self.path, "w", encoding="utf-8") as f:
            f.write((existing + _SEP + entry) if existing else ("# 协作日志\n\n" + entry))

    def recent(self, n: int = 3) -> list[str]:
        """返回最近 n 条日志条目(每条是一段文本),最新在最后。"""
        body = self._read()
        if not body:
            return []
        # 去掉文件标题,按 "## " 分条
        if body.startswith("# 协作日志"):
            body = body.split("\n", 2)[-1]
        chunks = [c.strip() for c in body.split(_SEP) if c.strip()]
        return chunks[-n:]

    def render_briefing(self, n: int = 2) -> str:
        """开场注入用的"上次到哪了"块;无内容返回空串。"""
        chunks = self.recent(n)
        if not chunks:
            return ""
        return ("[我们的协作进展 · 上次到哪了(供你接续,不必复述)]\n"
                + "\n\n".join(chunks))

    def _read(self) -> str:
        if not os.path.isfile(self.path):
            return ""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""


class JournalConsolidator:
    """会话结束时,把对话总结成一条协作日志写入 Journal。llm/journal 可注入便于测试。"""

    def __init__(self, llm, journal: Journal) -> None:
        self._llm = llm
        self._journal = journal

    async def consolidate(self, messages: list) -> bool:
        dialogue = _format_dialogue(messages)
        if not dialogue.strip():
            return False
        summary, decisions, next_steps = "", [], []
        try:
            from core.types import Message, Role
            step = await self._llm.next_step(
                [Message(role=Role.USER, content=_CONSOLIDATE_PROMPT.format(dialogue=dialogue))], [])
            m = re.search(r"\{.*\}", step.text or "", re.DOTALL)
            if m:
                data = json.loads(m.group())
                summary = str(data.get("summary", "")).strip()
                decisions = [str(x) for x in (data.get("decisions") or []) if str(x).strip()]
                next_steps = [str(x) for x in (data.get("next_steps") or []) if str(x).strip()]
        except Exception:
            pass
        # 优雅降级:模型调用失败/返回非 JSON 时,也别让这次会话凭空消失——
        # 用对话本身兜出一条最简日志(首个请求当摘要),保证记忆不丢。
        if not summary:
            summary = self._fallback_summary(messages)
        if not summary:
            return False
        try:
            self._journal.append(summary, decisions, next_steps)
            return True
        except Exception:
            return False

    @staticmethod
    def _fallback_summary(messages: list) -> str:
        from core.types import Role
        first_user = next((m.content for m in messages
                           if getattr(m, "role", None) == Role.USER and m.content), "")
        if not first_user:
            return ""
        head = first_user.strip().splitlines()[0][:80]
        return f"(自动记录·未及总结)本次围绕:{head}"


def _format_dialogue(messages: list, turns: int = _DIALOGUE_TURNS) -> str:
    from core.types import Role
    lines: list[str] = []
    for m in messages:
        if getattr(m, "role", None) == Role.USER and m.content:
            lines.append(f"主人: {m.content[:300]}")
        elif getattr(m, "role", None) == Role.ASSISTANT and m.content and not getattr(m, "tool_calls", None):
            lines.append(f"助理: {m.content[:200]}")
    return "\n".join(lines[-turns:])
