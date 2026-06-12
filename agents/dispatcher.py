"""意图路由器 —— 分析用户任务,决定派给哪些 agent、以什么顺序。

两级策略(自动降级):
  1. LLMDispatcher  用 LLM 分析任务语义,输出 JSON 分配方案
                    → 有依赖则串行,无依赖则并行(你选择的"自动"模式)
  2. KeywordDispatcher  关键词匹配兜底(LLM 失效 / 无 key 时)

返回格式 DispatchPlan:
  assignments: [(agent_name, sub_task), ...]  # 每个 agent 要做什么
  parallel:     bool                          # True=可并行,False=串行
  reason:       str                           # 路由理由(可观测性)

学习点:
  - 把"决策"和"执行"分开:Dispatcher 只出计划,不运行 agent。
  - LLM 输出 JSON 结构比自然语言更稳定,少幻觉。
  - 关键词兜底保证在任何环境下都能运行(eval/mock 时不需要 API)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Assignment:
    agent_name: str
    sub_task: str


@dataclass
class DispatchPlan:
    assignments: list[Assignment] = field(default_factory=list)
    parallel: bool = False   # True=可并行执行
    reason: str = ""

    def is_empty(self) -> bool:
        return not self.assignments


class LLMDispatcher:
    """用 LLM 分析任务并路由。"""

    def __init__(self, llm) -> None:
        self._llm = llm

    async def route(self, task: str, workers: list) -> DispatchPlan:
        if not workers:
            return DispatchPlan(reason="无可用 agent")

        # 构建 agent 清单描述
        roster_desc = "\n".join(
            f"  - {w.name}: {w.description or w.role}" for w in workers
        )
        prompt = f"""你是 Captain 的任务分配器。Captain 是总指挥,只负责对话与汇总;
执行型 worker 只动手、不思考,做完把结果交回 Captain。

根据用户任务决定:
1. 是否需派 worker(需动手执行才派;纯聊天/简单问答不派)
2. 派哪些 worker、各自具体执行什么
3. 是否可并行(True=相互独立,False=有先后依赖)

【由 Captain 直接处理,assignments 必须为 []】
- 闲聊、寒暄、自我介绍(如「你是谁」)
- 简单解释、商量、无需工具的单轮问答
- 让 Captain 自己总结已有对话、不做新执行

【应派给 worker 的典型场景】
- code_agent: 读写代码、跑 shell、调试与工程操作
- data_analyst_agent: CSV/JSON/日志统计分析与数据简报(产物在 logs/reports/)
- web_agent: 一键生成可打开的单页 HTML 落地页(可联网查素材)
- ops_notify_agent: 报告摘要推送至邮件/企微/QQ(唯一有真实推送权限)
- adler_counselor_agent: 阿德勒取向心理支持与长期记忆纪要(非医疗)

可用 worker:
{roster_desc}

用户任务:
{task}

请严格输出 JSON(不要有其他内容):
{{
  "assignments": [
    {{"agent": "worker名", "sub_task": "具体执行任务(可执行、可验收)"}},
    ...
  ],
  "parallel": true或false,
  "reason": "一句话说明为何派发或不派发"
}}"""

        from core.types import Message, Role
        messages = [Message(role=Role.USER, content=prompt)]
        try:
            step = await self._llm.next_step(messages, [])
            text = step.text or ""
            return _parse_plan(text, workers)
        except Exception as e:
            return DispatchPlan(reason=f"LLM 路由失败({e}),将降级到关键词匹配")


class KeywordDispatcher:
    """关键词匹配兜底路由,不消耗 LLM。"""

    def route(self, task: str, workers: list) -> DispatchPlan:
        task_lower = task.lower()
        matched: list[Assignment] = []
        for w in workers:
            keywords = getattr(getattr(w, "spec", None), "trigger_keywords", []) or []
            if any(kw.lower() in task_lower for kw in keywords):
                matched.append(Assignment(agent_name=w.name, sub_task=task))
        if not matched:
            # 无关键词命中 → 空计划,由主 agent 直接回答(避免「你是谁」之类被误派专家)
            return DispatchPlan(reason="无关键词命中,由主 agent 处理")
        return DispatchPlan(
            assignments=matched,
            parallel=len(matched) > 1,
            reason="关键词匹配",
        )


class AutoDispatcher:
    """主路由器:先尝试 LLM,失败则关键词兜底。"""

    def __init__(self, llm) -> None:
        self._llm_disp = LLMDispatcher(llm)
        self._kw_disp = KeywordDispatcher()

    async def route(self, task: str, workers: list) -> DispatchPlan:
        plan = await self._llm_disp.route(task, workers)
        if plan.is_empty() or "失败" in plan.reason:
            fallback = self._kw_disp.route(task, workers)
            if not fallback.is_empty():
                return fallback
        return plan


# ── 解析 LLM 输出 ─────────────────────────────────────────────────────────────

def _parse_plan(text: str, workers: list) -> DispatchPlan:
    """从 LLM 输出里提取 JSON 分配方案。"""
    worker_names = {w.name for w in workers}
    # 提取第一个 JSON 对象
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return DispatchPlan(reason=f"LLM 输出无法解析为 JSON: {text[:100]}")
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError as e:
        return DispatchPlan(reason=f"JSON 解析失败: {e}")

    assignments: list[Assignment] = []
    for item in data.get("assignments", []):
        name = item.get("agent", "")
        sub = item.get("sub_task", "")
        if name in worker_names and sub:
            assignments.append(Assignment(agent_name=name, sub_task=sub))

    return DispatchPlan(
        assignments=assignments,
        parallel=bool(data.get("parallel", False)),
        reason=str(data.get("reason", "")),
    )
