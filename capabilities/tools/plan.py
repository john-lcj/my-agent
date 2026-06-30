"""待办清单能力 —— 让单个 agent「先列计划、做一步勾一步」(像 Claude 那样)。

agent 在动手前用 plan.update 把任务拆成几步写进清单;每完成一步就再调一次更新状态。
真正的 UI 渲染由 loop 把这次调用翻译成 plan_update 事件(复用右侧 Progress 面板)。
本能力只负责校验入参 + 回一句确认,属只读(不写盘、不弹确认)。
"""
from __future__ import annotations

from typing import Any

from core.types import CapabilityResult, Risk

_STATUSES = {"todo", "pending", "doing", "running", "done", "failed"}


def normalize_steps(raw: Any) -> list[dict]:
    """把入参规整成 [{'text':..., 'status':..., 'check':...}],容忍字符串列表或字典列表。"""
    steps: list[dict] = []
    for item in (raw or []):
        if isinstance(item, str):
            text, status, check = item.strip(), "todo", ""
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("task") or item.get("step") or "").strip()
            status = str(item.get("status") or "todo").strip().lower()
            check = str(item.get("check") or item.get("criteria") or item.get("verify") or "").strip()
        else:
            continue
        if not text:
            continue
        if status not in _STATUSES:
            status = "todo"
        row = {"text": text[:120], "status": status}
        if check:
            row["check"] = check[:160]
        steps.append(row)
    return steps


class PlanUpdate:
    name = "plan.update"
    risk = Risk.READ
    description = ("维护你的待办清单:把任务拆成几步,每步带状态和可选验收标准 check。动手前先列计划,"
                  "每完成一步就再调一次更新状态。状态:todo(待办)/doing(进行中)/done(完成)/failed(失败)。")
    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "完整的当前待办清单(每次传全量,不是增量)",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "这一步要做什么"},
                        "status": {"type": "string", "enum": ["todo", "doing", "done", "failed"]},
                        "check": {"type": "string", "description": "这一步怎么判断完成(可选,建议复杂任务填写)"},
                    },
                    "required": ["text"],
                },
            }
        },
        "required": ["steps"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        steps = normalize_steps(args.get("steps"))
        if not steps:
            return CapabilityResult(ok=False, error="steps 为空")
        done = sum(1 for s in steps if s["status"] == "done")
        doing = sum(1 for s in steps if s["status"] in ("doing", "running"))
        # 真正的事件渲染在 loop 里(它能拿到事件总线);这里只回执行回执给模型。
        with_check = sum(1 for s in steps if s.get("check"))
        return CapabilityResult(
            ok=True,
            output=f"待办已更新:共 {len(steps)} 步,完成 {done},进行中 {doing},含验收 {with_check}。继续推进下一步。",
        )
