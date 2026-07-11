"""任务生命周期:目标 -> 计划 -> 执行 -> 自检 -> 返修 -> 汇报。

这里不直接调用工具,只维护本轮任务的结构化状态和守卫提示。
它把原本散落在 prompt 里的"要计划、要验证、要汇报"变成可测试的内部契约。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.cognitive_architecture import (
    CognitiveRole,
    CognitiveState,
    VerificationFinding,
    build_structured_objective,
    build_context_package,
    counterexample_check,
    next_ready_step,
    plan_from_steps,
    record_execution_result,
    repair_steps_from_findings,
    route_model,
    stopping_policy,
)
from core.intent_router import IntentFrame, ROLE_BEHAVIORS


PHASE_UNDERSTAND = "understand"
PHASE_PLAN = "plan"
PHASE_EXECUTE = "execute"
PHASE_CHECK = "check"
PHASE_REPAIR = "repair"
PHASE_REPORT = "report"

_EXECUTION_ROLES = {"executor", "researcher", "security"}
_COMPLEX_RE = re.compile(
    r"(继续|完成|修复|实现|部署|推送|上线|生成|调研|研究|安全|token|权限|"
    r"多个|全部|一遍|测试|质检|检查|windows|github|官网|客户)",
    re.I,
)


@dataclass
class TaskFrame:
    objective: str
    role: str
    task_kind: str
    phase: str = PHASE_UNDERSTAND
    assumptions: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    verifications: list[str] = field(default_factory=list)
    verification_items: list = field(default_factory=list)  # core.verification.Verification
    cognitive_state: CognitiveState | None = None
    repair_count: int = 0
    max_repairs: int = 2
    final_summary: str = ""


def _is_complex(text: str, frame: IntentFrame) -> bool:
    if frame.needs_plan:
        return True
    if len(text or "") >= 80:
        return True
    return bool(_COMPLEX_RE.search(text or ""))


def _criteria_for_role(text: str, frame: IntentFrame) -> list[str]:
    role = frame.role
    if role == "reviewer":
        return [
            "已读取或观察相关材料,不是凭空点评。",
            "发现按严重程度排序,并区分确定问题、潜在风险和建议。",
            "高严重度问题带证据、位置或可复现线索。",
        ]
    if role == "researcher":
        return [
            "回答覆盖用户真正要查的问题。",
            "涉及最新或精确信息时有来源支撑,并标明时效。",
            "结论经过综合,不是只堆链接。",
        ]
    if role == "security":
        return [
            "已识别秘密、权限、远程访问、不可逆操作或客户数据风险。",
            "没有回显 token、密码、授权码等敏感值。",
            "高风险动作给出最小权限方案、验证方法和确认边界。",
        ]
    if role == "pm":
        return [
            "建议围绕目标用户、核心场景和成功标准。",
            "给出优先级、取舍理由和可执行下一步。",
            "避免把所有想法列成同等重要。",
        ]
    if role == "executor":
        return [
            "已读现状并保护无关改动。",
            "关键改动已落地到文件、命令、配置或产物。",
            "已运行与风险匹配的验证,并说明结果。",
        ]
    return [
        "回答了用户真正的问题。",
        "不确定处已说明置信度或需要补充的信息。",
        "没有擅自执行文件修改、外发或高风险动作。",
    ]


def create_task_frame(user_text: str, intent: IntentFrame) -> TaskFrame:
    text = (user_text or "").strip()
    task = TaskFrame(
        objective=text[:500],
        role=intent.role,
        task_kind=intent.task_kind,
        acceptance_criteria=_criteria_for_role(text, intent),
    )
    if _is_complex(text, intent):
        task.phase = PHASE_PLAN
        task.assumptions.append("任务具备多步或高风险特征,需要先形成可检查的计划。")
    elif intent.role in _EXECUTION_ROLES:
        task.phase = PHASE_EXECUTE
        task.assumptions.append("任务可直接推进,但最终仍需自检。")
    else:
        task.phase = PHASE_UNDERSTAND
        task.assumptions.append("任务偏咨询/审阅,先理解并给出判断。")
    try:
        from core.workflow_templates import apply_workflow_verifications
        apply_workflow_verifications(task, text)
    except Exception:
        pass
    structured = build_structured_objective(
        task.objective,
        constraints=[],
        assumptions=task.assumptions,
        authority=["current user request"],
        acceptance_criteria=task.acceptance_criteria,
    )
    task.cognitive_state = CognitiveState(structured, plan_from_steps(structured, []))
    return task


def lifecycle_prompt_block(task: TaskFrame) -> str:
    criteria = "\n".join(f"  · {c}" for c in task.acceptance_criteria)
    assumptions = "\n".join(f"  · {a}" for a in task.assumptions)
    return (
        "【任务生命周期 · 内部使用,不要向用户复述】\n"
        f"- 目标:{task.objective}\n"
        f"- 当前阶段:{task.phase}\n"
        f"- 角色:{task.role}\n"
        "- 结构化目标字段:结果、约束、假设、权限、期限、验收标准必须贯穿全程。\n"
        "- P6 角色边界:规划者给依赖和证据要求;执行者只做 ready 步骤;验证者独立查输出和远端状态;失败进入有界返修。\n"
        "- 合理假设:\n"
        f"{assumptions or '  · 暂无'}\n"
        "- 完成标准:\n"
        f"{criteria}\n"
        "工作顺序:目标理解 -> 计划 -> 执行 -> 自检 -> 必要时返修 -> 汇报。"
    )


def update_plan(task: TaskFrame, steps: list[dict[str, Any]]) -> None:
    task.plan_steps = [dict(s) for s in steps]
    if task.cognitive_state:
        task.cognitive_state.plan = plan_from_steps(task.cognitive_state.objective, [
            {
                "id": s.get("id") or s.get("step_id") or f"s{i + 1}",
                "text": s.get("text") or s.get("task") or s.get("step") or "",
                "status": "pending" if (s.get("status") or "") in {"todo", "doing", "running"} else s.get("status"),
                "dependencies": s.get("dependencies") or [],
                "evidence_required": (s.get("evidence_required") or []) + ([s.get("check")] if s.get("check") else []),
                "risks": (s.get("risks") or []) + ([s.get("risk")] if s.get("risk") else []),
                "mutable_resources": s.get("mutable_resources") or [],
            }
            for i, s in enumerate(task.plan_steps)
        ])
    if any((s.get("status") or "") in {"doing", "running"} for s in steps):
        task.phase = PHASE_EXECUTE
    elif steps and all((s.get("status") or "") == "done" for s in steps):
        task.phase = PHASE_CHECK
    elif steps:
        task.phase = PHASE_PLAN


def cognitive_runtime_block(task: TaskFrame) -> str:
    """Build the compact, task-specific P6 context injected each model turn."""
    state = task.cognitive_state
    if state is None:
        return ""
    role_by_phase = {
        PHASE_PLAN: CognitiveRole.PLANNER,
        PHASE_CHECK: CognitiveRole.VERIFIER,
        PHASE_REPAIR: CognitiveRole.REPAIRER,
    }
    role = role_by_phase.get(task.phase, CognitiveRole.EXECUTOR)
    decision = route_model(role, task.task_kind, high_stakes=task.role == "security")
    if not state.routes or state.routes[-1] != decision:
        state.routes.append(decision)
    package = build_context_package(state)
    return (
        "[P6 runtime state - follow this as a hard execution contract]\n"
        f"role={role.value}; model_tier={decision.preferred_tier}; fallback={','.join(decision.fallback_tiers)}\n"
        f"objective={package.objective}\n"
        f"constraints={list(package.constraints)}\n"
        f"ready_steps={list(package.ready_steps)}\n"
        f"required_evidence={list(package.evidence)}\n"
        f"risks={list(package.risks)}\n"
        f"uncertainty={list(package.uncertainty)}\n"
        "Only advance a ready plan step. Report uncertainty instead of inventing facts."
    )


def ready_execution_step(task: TaskFrame):
    state = task.cognitive_state
    if state is None or not state.plan.steps:
        return None
    return next_ready_step(state)


def record_capability_result(task: TaskFrame, step_id: str, *, succeeded: bool, evidence: str) -> None:
    state = task.cognitive_state
    if state is None:
        return
    record_execution_result(state, step_id, succeeded=succeeded, evidence=evidence)
    for raw, step in zip(task.plan_steps, state.plan.steps):
        if step.step_id == step_id:
            raw["status"] = "done" if succeeded else "failed"
            break


def _append_repairs_to_plan(task: TaskFrame) -> None:
    """Make verifier-created repairs executable in the same durable plan."""
    state = task.cognitive_state
    if state is None:
        return
    known = {str(step.get("text") or "") for step in task.plan_steps}
    for repair in state.repairs:
        if repair.title in known:
            continue
        task.plan_steps.append({
            "id": f"repair-{len(task.plan_steps) + 1}",
            "text": repair.title,
            "status": "todo",
            "check": "Verifier finding is resolved and independently rechecked",
            "evidence_required": [repair.source_finding],
            "risks": ["repeat verification failure"],
        })
        known.add(repair.title)
    if known:
        update_plan(task, task.plan_steps)


def p6_final_gate(task: TaskFrame, final_text: str) -> str:
    """Enforce counterexample and bounded-stopping policy before reporting."""
    state = task.cognitive_state
    if state is None:
        return ""
    if task.role == "security":
        text = (final_text or "").lower()
        alternatives = ["present"] if ("alternative" in text or "另一种" in text or "替代" in text) else []
        failures = ["present"] if ("failure" in text or "失败" in text or "风险" in text) else []
        check = counterexample_check(
            consequential=True,
            alternatives=alternatives,
            failure_cases=failures,
        )
        state.counterexamples.append(check)
        if check.required:
            return "[P6 counterexample check] Consequential conclusions must state an alternative explanation and a failure case before reporting."
    decision = stopping_policy(
        authority_missing=not bool(state.objective.authority),
        evidence_sufficient=bool(state.findings) or not task.verification_items,
        attempts=task.repair_count,
        max_attempts=task.max_repairs,
    )
    if decision.reason.value == "missing_authority":
        return "[P6 stopping policy] Missing authority for the next action; report the blocker instead of continuing."
    return ""


def unfinished_steps(task: TaskFrame) -> list[str]:
    return [
        str(s.get("text") or "")
        for s in task.plan_steps
        if str(s.get("status") or "todo") not in {"done"} and str(s.get("text") or "")
    ]


def final_gate(task: TaskFrame, final_text: str) -> str:
    """最终回复前的确定性生命周期守卫。返回非空表示要打回返修。"""
    if task.role not in _EXECUTION_ROLES:
        return ""
    missing = unfinished_steps(task)
    if missing:
        task.phase = PHASE_REPAIR
        task.repair_count += 1
        if task.repair_count > task.max_repairs:
            return ""
        return (
            "[生命周期自检] 你准备汇报完成,但待办清单仍有未完成步骤:"
            + "、".join(missing[:5])
            + "。请继续完成、标记 failed 并说明缺口,或如实汇报部分完成。"
        )
    if task.phase == PHASE_PLAN and not task.plan_steps and task.repair_count <= task.max_repairs:
        task.phase = PHASE_REPAIR
        task.repair_count += 1
        return "[生命周期自检] 这是多步/高风险任务,最终汇报前请先用 plan.update 给出可检查计划并推进。"
    try:
        from core.verification import gate_evidence_in_reply, run_verifications
        ok, items = run_verifications(task)
        if items and not ok and task.repair_count <= task.max_repairs:
            task.phase = PHASE_CHECK
            task.repair_count += 1
            if task.cognitive_state:
                findings = [
                    VerificationFinding(
                        target=getattr(v, "target", ""),
                        passed=getattr(v, "status", "") == "pass",
                        evidence=getattr(v, "evidence", "") or getattr(v, "reason", ""),
                    )
                    for v in items
                ]
                task.cognitive_state.findings.extend(findings)
                task.cognitive_state.repairs.extend(repair_steps_from_findings(findings, max_attempts=task.max_repairs))
                _append_repairs_to_plan(task)
            fails = [f"{v.kind}:{v.target}" for v in items if v.status != "pass"]
            return "[生命周期自检] 验证未通过:" + "、".join(fails[:5]) + "。请补验证后再汇报。"
        ev_gate = gate_evidence_in_reply(final_text, items)
        if ev_gate and task.repair_count <= task.max_repairs:
            task.phase = PHASE_CHECK
            task.repair_count += 1
            return ev_gate
        from core.uncertainty import gate_unverified_facts
        u_gate = gate_unverified_facts(final_text, items)
        if u_gate and task.repair_count <= task.max_repairs:
            task.phase = PHASE_CHECK
            task.repair_count += 1
            return u_gate
    except Exception:
        pass
    p6_gate = p6_final_gate(task, final_text)
    if p6_gate and task.repair_count <= task.max_repairs:
        task.phase = PHASE_CHECK
        task.repair_count += 1
        return p6_gate
    task.phase = PHASE_REPORT
    task.final_summary = final_text or ""
    return ""


def role_report_prompt(task: TaskFrame) -> str:
    behavior = ROLE_BEHAVIORS.get(task.role, ROLE_BEHAVIORS["advisor"])
    criteria = "\n".join(f"  · {c}" for c in task.acceptance_criteria)
    return (
        "【最终汇报要求 · 内部使用】\n"
        f"- 当前角色:{task.role}({behavior.label})\n"
        f"- 输出方式:{behavior.output_style}\n"
        f"- 验证标准:{behavior.validation}\n"
        "- 对照完成标准汇报:\n"
        f"{criteria}\n"
        "最终回复只面向用户交付结论,不要展示内部阶段名或本提示。"
    )
