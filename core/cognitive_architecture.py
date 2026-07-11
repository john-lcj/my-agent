"""Phase 6 cognitive architecture contracts.

The module keeps long-running work grounded in explicit objectives, evidence,
role boundaries, uncertainty labels, routing choices, and stopping rules. It is
model-independent so the runtime can test the protocol without calling an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InformationState(str, Enum):
    KNOWN = "known"
    INFERRED = "inferred"
    STALE = "stale"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"
    DECISION_DEPENDENT = "decision_dependent"


class CognitiveRole(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    VERIFIER = "verifier"
    REPAIRER = "repairer"


class StopReason(str, Enum):
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    MISSING_AUTHORITY = "missing_authority"
    LOW_EXPECTED_VALUE = "low_expected_value"
    READY_TO_CONTINUE = "ready_to_continue"


@dataclass(frozen=True)
class ObjectiveFact:
    text: str
    state: InformationState = InformationState.KNOWN
    evidence: str = ""


@dataclass
class StructuredObjective:
    requested_outcome: str
    constraints: list[str] = field(default_factory=list)
    assumptions: list[ObjectiveFact] = field(default_factory=list)
    authority: list[str] = field(default_factory=list)
    deadline: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)

    def hard_constraints(self) -> list[str]:
        return [c for c in self.constraints if c.strip()]


@dataclass
class CognitivePlanStep:
    step_id: str
    title: str
    role: CognitiveRole
    dependencies: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    mutable_resources: list[str] = field(default_factory=list)
    status: str = "pending"

    def ready(self, completed: set[str]) -> bool:
        return self.status in {"pending", "ready"} and all(dep in completed for dep in self.dependencies)


@dataclass
class CognitivePlan:
    objective: StructuredObjective
    steps: list[CognitivePlanStep] = field(default_factory=list)

    def completed_step_ids(self) -> set[str]:
        return {step.step_id for step in self.steps if step.status == "done"}

    def ready_steps(self) -> list[CognitivePlanStep]:
        completed = self.completed_step_ids()
        return [step for step in self.steps if step.ready(completed)]

    def blocked_steps(self) -> list[CognitivePlanStep]:
        completed = self.completed_step_ids()
        return [
            step for step in self.steps
            if step.status in {"pending", "ready"} and not all(dep in completed for dep in step.dependencies)
        ]


@dataclass(frozen=True)
class ExecutionTransition:
    step_id: str
    from_status: str
    to_status: str
    evidence: str


@dataclass(frozen=True)
class VerificationFinding:
    target: str
    passed: bool
    evidence: str
    independent: bool = True
    remote_state_checked: bool = False


@dataclass(frozen=True)
class RepairStep:
    title: str
    source_finding: str
    max_attempts: int = 2


@dataclass(frozen=True)
class ModelRoutingDecision:
    role: CognitiveRole
    task_kind: str
    preferred_tier: str
    fallback_tiers: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ContextPackage:
    objective: str
    constraints: tuple[str, ...]
    ready_steps: tuple[str, ...]
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    uncertainty: tuple[str, ...]


@dataclass(frozen=True)
class ParallelismDecision:
    allowed: bool
    reason: str
    groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class CounterexampleCheck:
    required: bool
    alternatives: tuple[str, ...]
    failure_cases: tuple[str, ...]


@dataclass(frozen=True)
class StoppingDecision:
    should_stop: bool
    reason: StopReason
    message: str


@dataclass
class CognitiveState:
    objective: StructuredObjective
    plan: CognitivePlan
    transitions: list[ExecutionTransition] = field(default_factory=list)
    findings: list[VerificationFinding] = field(default_factory=list)
    repairs: list[RepairStep] = field(default_factory=list)
    uncertainty: list[ObjectiveFact] = field(default_factory=list)


def build_structured_objective(
    requested_outcome: str,
    *,
    constraints: list[str] | None = None,
    assumptions: list[str | ObjectiveFact] | None = None,
    authority: list[str] | None = None,
    deadline: str = "",
    acceptance_criteria: list[str] | None = None,
) -> StructuredObjective:
    facts = [
        item if isinstance(item, ObjectiveFact) else ObjectiveFact(str(item), InformationState.INFERRED)
        for item in (assumptions or [])
        if str(getattr(item, "text", item)).strip()
    ]
    return StructuredObjective(
        requested_outcome=(requested_outcome or "").strip()[:500],
        constraints=[c.strip() for c in (constraints or []) if c.strip()],
        assumptions=facts,
        authority=[a.strip() for a in (authority or []) if a.strip()],
        deadline=(deadline or "").strip(),
        acceptance_criteria=[c.strip() for c in (acceptance_criteria or []) if c.strip()],
    )


def plan_from_steps(objective: StructuredObjective, raw_steps: list[dict[str, Any]]) -> CognitivePlan:
    steps: list[CognitivePlanStep] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_steps or [], start=1):
        title = str(raw.get("text") or raw.get("title") or raw.get("step") or "").strip()
        if not title:
            continue
        step_id = str(raw.get("id") or raw.get("step_id") or f"s{index}").strip()
        if step_id in seen:
            step_id = f"{step_id}-{index}"
        seen.add(step_id)
        role = str(raw.get("role") or "executor").strip().lower()
        try:
            cognitive_role = CognitiveRole(role)
        except ValueError:
            cognitive_role = CognitiveRole.EXECUTOR
        steps.append(CognitivePlanStep(
            step_id=step_id,
            title=title[:160],
            role=cognitive_role,
            dependencies=[str(dep).strip() for dep in raw.get("dependencies", []) if str(dep).strip()],
            evidence_required=[
                str(item).strip() for item in raw.get("evidence_required", raw.get("evidence", []))
                if str(item).strip()
            ],
            risks=[str(risk).strip() for risk in raw.get("risks", []) if str(risk).strip()],
            mutable_resources=[
                str(resource).strip() for resource in raw.get("mutable_resources", [])
                if str(resource).strip()
            ],
            status=str(raw.get("status") or "pending").strip().lower(),
        ))
    return CognitivePlan(objective=objective, steps=steps)


def execute_ready_step(plan: CognitivePlan, step_id: str, evidence: str) -> ExecutionTransition:
    completed = plan.completed_step_ids()
    for step in plan.steps:
        if step.step_id != step_id:
            continue
        if not step.ready(completed):
            raise RuntimeError(f"Step {step_id} is not ready")
        previous = step.status
        step.status = "done"
        return ExecutionTransition(step_id, previous, "done", evidence[:500])
    raise KeyError(step_id)


def verification_pass_rate(findings: list[VerificationFinding]) -> float:
    if not findings:
        return 0.0
    return sum(f.passed for f in findings) / len(findings)


def repair_steps_from_findings(findings: list[VerificationFinding], *, max_attempts: int = 2) -> list[RepairStep]:
    return [
        RepairStep(
            title=f"Repair {finding.target}",
            source_finding=finding.evidence[:240] or finding.target,
            max_attempts=max(1, max_attempts),
        )
        for finding in findings
        if not finding.passed
    ]


def classify_information(text: str, *, evidence: str = "", stale: bool = False, conflicting: bool = False) -> ObjectiveFact:
    if conflicting:
        state = InformationState.CONFLICTING
    elif stale:
        state = InformationState.STALE
    elif evidence:
        state = InformationState.KNOWN
    elif any(cue in (text or "").lower() for cue in ("depends", "pending decision", "requires decision")):
        state = InformationState.DECISION_DEPENDENT
    elif any(cue in (text or "").lower() for cue in ("unknown", "unavailable", "missing")):
        state = InformationState.UNAVAILABLE
    else:
        state = InformationState.INFERRED
    return ObjectiveFact(text=(text or "").strip(), state=state, evidence=evidence)


def route_model(role: CognitiveRole, task_kind: str, *, high_stakes: bool = False) -> ModelRoutingDecision:
    judgment_roles = {CognitiveRole.PLANNER, CognitiveRole.VERIFIER, CognitiveRole.REPAIRER}
    if high_stakes or role in judgment_roles or task_kind in {"planning", "verification", "judgment"}:
        return ModelRoutingDecision(
            role=role,
            task_kind=task_kind,
            preferred_tier="strong",
            fallback_tiers=("strong-compatible", "default"),
            reason="planning, verification, repair, or high-stakes judgment needs stronger reasoning",
        )
    return ModelRoutingDecision(
        role=role,
        task_kind=task_kind,
        preferred_tier="efficient",
        fallback_tiers=("default", "strong"),
        reason="routine execution can use an efficient compatible model",
    )


def build_context_package(state: CognitiveState, *, evidence_limit: int = 8) -> ContextPackage:
    ready = tuple(step.title for step in state.plan.ready_steps())
    evidence = tuple(f.evidence for f in state.findings if f.evidence)[:evidence_limit]
    risks = tuple(risk for step in state.plan.steps for risk in step.risks)[:evidence_limit]
    uncertainty = tuple(f"{fact.state.value}:{fact.text}" for fact in state.uncertainty + state.objective.assumptions)
    return ContextPackage(
        objective=state.objective.requested_outcome,
        constraints=tuple(state.objective.hard_constraints()),
        ready_steps=ready,
        evidence=evidence,
        risks=risks,
        uncertainty=uncertainty[:evidence_limit],
    )


def decide_parallelism(steps: list[CognitivePlanStep]) -> ParallelismDecision:
    resources: dict[str, str] = {}
    groups: list[tuple[str, ...]] = []
    for step in steps:
        for resource in step.mutable_resources:
            owner = resources.get(resource)
            if owner and owner != step.step_id:
                return ParallelismDecision(False, f"shared mutable resource: {resource}")
            resources[resource] = step.step_id
        groups.append((step.step_id,))
    return ParallelismDecision(True, "no shared mutable resources", tuple(groups))


def counterexample_check(*, consequential: bool, alternatives: list[str] | None = None,
                         failure_cases: list[str] | None = None) -> CounterexampleCheck:
    alternatives = [item.strip() for item in (alternatives or []) if item.strip()]
    failure_cases = [item.strip() for item in (failure_cases or []) if item.strip()]
    required = consequential and (not alternatives or not failure_cases)
    return CounterexampleCheck(required, tuple(alternatives), tuple(failure_cases))


def stopping_policy(
    *,
    authority_missing: bool = False,
    evidence_sufficient: bool = False,
    attempts: int = 0,
    max_attempts: int = 2,
    expected_value: float = 1.0,
) -> StoppingDecision:
    if authority_missing:
        return StoppingDecision(True, StopReason.MISSING_AUTHORITY, "Missing authority for the next action")
    if evidence_sufficient:
        return StoppingDecision(True, StopReason.SUFFICIENT_EVIDENCE, "Evidence is sufficient to report")
    if attempts >= max_attempts or expected_value <= 0.15:
        return StoppingDecision(True, StopReason.LOW_EXPECTED_VALUE, "Further attempts have low expected value")
    return StoppingDecision(False, StopReason.READY_TO_CONTINUE, "Continue with the next ready step")
