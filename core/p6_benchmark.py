"""Deterministic Phase 6 long-horizon acceptance benchmark.

It deliberately avoids external models and accounts so it can run in CI.  The
benchmark exercises the same task-lifecycle transition functions that the live
loop uses for dependency gating and durable execution evidence.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from core.cognitive_architecture import (
    VerificationFinding,
    decide_parallelism,
    repair_steps_from_findings,
    stopping_policy,
)
from core.intent_router import classify_intent
from core.task_lifecycle import (
    create_task_frame,
    final_gate,
    ready_execution_step,
    record_capability_result,
    update_plan,
)
from core.types import CapabilityCall, Message, Role, Step, ToolCallRef


def _fallback_contract_is_preserved() -> bool:
    """Exercise the real fallback wrapper with a paired tool-call history."""
    from llm.fallback import FallbackLLM

    class FailingPrimary:
        name = "primary"

        async def next_step(self, messages, capabilities, emit_token=None):
            raise RuntimeError("seeded primary failure")

    class WorkingBackup:
        name = "backup"

        async def next_step(self, messages, capabilities, emit_token=None):
            paired = any(
                message.role == Role.TOOL and message.tool_call_id == "call-1"
                for message in messages
            )
            return Step(text="fallback accepted paired history" if paired else "history corrupted")

    history = [
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCallRef(id="call-1", name="noop", args={})],
        ),
        Message(role=Role.TOOL, content="ok", tool_call_id="call-1", name="noop"),
    ]
    result = asyncio.run(FallbackLLM(FailingPrimary(), [WorkingBackup()]).next_step(history, []))
    return result.text == "fallback accepted paired history"


@dataclass(frozen=True)
class P6BenchmarkReport:
    meaningful_steps: int
    constraint_retention_rate: float
    false_completion_rate: float
    seeded_defect_capture_rate: float
    fallback_contract_preserved: bool
    parallelism_safe: bool
    stopping_policy_safe: bool

    @property
    def passed(self) -> bool:
        return (
            self.meaningful_steps >= 50
            and self.constraint_retention_rate == 1.0
            and self.false_completion_rate < 0.02
            and self.seeded_defect_capture_rate >= 0.95
            and self.fallback_contract_preserved
            and self.parallelism_safe
            and self.stopping_policy_safe
        )


def run_p6_long_horizon_benchmark(*, step_count: int = 50, defect_count: int = 20) -> P6BenchmarkReport:
    if step_count < 50:
        raise ValueError("P6 benchmark requires at least 50 meaningful steps")
    if defect_count < 1:
        raise ValueError("P6 benchmark requires at least one seeded defect")

    task = create_task_frame("Complete a controlled P6 long-horizon workflow", classify_intent("完成 P6 并验证"))
    assert task.cognitive_state is not None
    state = task.cognitive_state
    state.objective.constraints = ["preserve hard constraints", "do not claim unverified completion"]
    steps = [
        {
            "id": f"s{i}",
            "text": f"Meaningful workflow step {i}",
            "status": "todo",
            "dependencies": [] if i == 1 else [f"s{i - 1}"],
            "evidence_required": [f"evidence-{i}"],
            "mutable_resources": [f"resource-{i}"],
        }
        for i in range(1, step_count + 1)
    ]
    update_plan(task, steps)

    # A premature final report must be caught before any work is accepted.
    premature_reports = 1
    caught_premature_reports = int(bool(final_gate(task, "Workflow completed.")))
    # The gate uses a bounded repair counter; restore the execution phase for
    # the intended controlled run after measuring the attempted false claim.
    task.repair_count = 0

    retained_constraints = 0
    for i in range(1, step_count + 1):
        ready = ready_execution_step(task)
        if ready is None or ready.step_id != f"s{i}":
            raise AssertionError(f"dependency guard failed at step {i}")
        record_capability_result(task, ready.step_id, succeeded=True, evidence=f"evidence-{i}")
        retained_constraints += int(state.objective.hard_constraints() == [
            "preserve hard constraints", "do not claim unverified completion",
        ])

    seeded = [
        VerificationFinding(
            target=f"seeded-defect-{i}",
            passed=False,
            evidence=f"defect-{i} detected by independent verifier",
            independent=True,
            remote_state_checked=True,
        )
        for i in range(1, defect_count + 1)
    ]
    repairs = repair_steps_from_findings(seeded)
    caught_defects = sum(1 for repair in repairs if repair.source_finding.startswith("defect-"))

    independent = decide_parallelism(state.plan.steps).allowed
    # Reuse resource deliberately to prove that the runtime will reject it.
    state.plan.steps[1].mutable_resources = list(state.plan.steps[0].mutable_resources)
    shared_rejected = not decide_parallelism([state.plan.steps[0], state.plan.steps[1]]).allowed
    state.plan.steps[1].mutable_resources = ["resource-2"]

    return P6BenchmarkReport(
        meaningful_steps=step_count,
        constraint_retention_rate=retained_constraints / step_count,
        false_completion_rate=(premature_reports - caught_premature_reports) / premature_reports,
        seeded_defect_capture_rate=caught_defects / defect_count,
        fallback_contract_preserved=_fallback_contract_is_preserved(),
        parallelism_safe=independent and shared_rejected,
        stopping_policy_safe=stopping_policy(evidence_sufficient=True).should_stop
        and stopping_policy(authority_missing=True).should_stop,
    )
