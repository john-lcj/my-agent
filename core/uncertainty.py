"""不确定性标记 —— 未查证信息须明示。"""
from __future__ import annotations

import re

_UNVERIFIED_CUES = re.compile(
    r"(据说|可能|大概|也许|未验证|未查证|听说|猜测|不确定|无法确认)",
)


def reply_needs_citation(text: str, had_web_tool: bool = False) -> bool:
    """回复含时效/事实断言但本轮未用检索工具时,建议补来源或降置信。"""
    if had_web_tool:
        return False
    t = text or ""
    if len(t) < 80:
        return False
    if _UNVERIFIED_CUES.search(t):
        return False
    if re.search(r"\d{4}年|\d+%|最新|目前|现已", t):
        return True
    return False


def uncertainty_prompt() -> str:
    return (
        "[未查证提醒] 你给出了可能依赖外部事实的断言,但本轮未见检索/读文件证据。"
        "请在回复中标注哪些已核实、哪些未查证,或先查证再答。"
    )


def gate_unverified_facts(final_text: str, verifications: list) -> str:
    """回复含具体数字/日期但无验证来源时打回。"""
    text = final_text or ""
    if not text:
        return ""
    has_source = any(
        getattr(v, "status", "") == "pass" and getattr(v, "evidence", "")
        for v in (verifications or [])
    )
    if has_source:
        return ""
    if re.search(r"\d{4}年|\d+%|\d+\.\d+", text) and not _UNVERIFIED_CUES.search(text):
        return uncertainty_prompt()
    return ""
