"""Skill 路由 —— 根据用户任务文本匹配应调用的 skill。"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillRoute:
    name: str  # 不含 skill. 前缀
    args: dict
    reason: str


# (关键词正则片段, skill, args 工厂, reason)
_RULES: list[tuple[str, str, str]] = [
    (
        r"落地页|landing|单页|活动页|作品集|portfolio|改版|前端页面|做个页面|html\s*页|网页制作",
        "design_taste_frontend",
        "design_read",
        "前端/落地页/作品集类任务",
    ),
    (
        r"设计|原型|prototype|mockup|deck|幻灯片|视觉稿|ui\s*设计|ux|keynote|演示页",
        "claude_design",
        "workflow",
        "设计流程与 artifact 交付",
    ),
    (
        r"推送|发邮件|企微|企业微信|qq\s*通知|群发|运营通知|日报推送|告警通知",
        "notify_dispatch",
        "hint",
        "外发通知(需主人确认或已配置凭证)",
    ),
    (
        r"我(的)?笔记|我之前写过|我(的)?文档|我记过|笔记里|我之前(的)?想法",
        "personal_search",
        "query",
        "个人笔记/文档语义检索",
    ),
    (
        r"关键词|标签|词频|卖点提炼|主题词",
        "keyword_extract",
        "tool",
        "文本关键词提取",
    ),
    (
        r"字数|篇幅|多少字|行数|词数|统计.{0,4}字",
        "text_stats",
        "tool",
        "精确字数/行数统计",
    ),
    (
        r"可读性|句长|润色.{0,4}评|过长句",
        "readability_score",
        "tool",
        "文案可读性分析",
    ),
]

_CHAT_ONLY = re.compile(
    r"^(你好|嗨|hi|hello|谢谢|好的|嗯|在吗|你是谁|你能做什么)[\s!?。.~]*$",
    re.I,
)


def _args_for(skill: str, mode: str, user_text: str) -> dict:
    brief = user_text.strip()[:600]
    if mode == "design_read":
        return {"action": "design_read", "brief": brief}
    if mode == "workflow":
        return {"action": "workflow", "brief": brief}
    if mode == "preflight":
        return {"action": "preflight", "brief": brief}
    if mode == "hint":
        return {"action": "overview"}
    if mode == "tool":
        return {"text": brief}
    if mode == "query":
        return {"query": brief}
    return {"action": "overview", "brief": brief}


def should_route(text: str) -> bool:
    t = (text or "").strip()
    if not t or t.startswith("/"):
        return False
    if _CHAT_ONLY.match(t):
        return False
    return bool(match_routes(t))


def match_routes(text: str, *, max_routes: int = 3) -> list[SkillRoute]:
    """返回按优先级去重后的 skill 路由列表。"""
    t = (text or "").strip()
    if not t:
        return []

    seen: set[str] = set()
    out: list[SkillRoute] = []

    for pattern, skill, mode, reason in _RULES:
        if skill in seen:
            continue
        if re.search(pattern, t, re.I):
            seen.add(skill)
            out.append(SkillRoute(skill, _args_for(skill, mode, t), reason))
            if len(out) >= max_routes:
                break

    # 前端类任务：交付前检查作为第二条 design_taste 路由（合并进预加载时只取 design_read）
    return out


# READ risk skills 可在循环开始前预加载；WRITE 仅提示路由，不自动执行。
# 指导型 skill(claude_design/design_taste) 内容过长,不预加载(由 agent 按需调用)。
_PREFETCH_OK = frozenset({
    "keyword_extract",
    "text_stats",
    "readability_score",
    "personal_search",
})


def routes_to_prefetch(routes: list[SkillRoute]) -> list[SkillRoute]:
    return [r for r in routes if r.name in _PREFETCH_OK]
