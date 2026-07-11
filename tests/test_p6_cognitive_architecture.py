from __future__ import annotations

from core.cognitive_architecture import (
    CognitiveRole,
    CognitiveState,
    InformationState,
    StopReason,
    VerificationFinding,
    build_context_package,
    build_structured_objective,
    classify_information,
    counterexample_check,
    decide_parallelism,
    execute_ready_step,
    plan_from_steps,
    repair_steps_from_findings,
    route_model,
    stopping_policy,
)
from core.intent_router import classify_intent
from core.task_lifecycle import create_task_frame, update_plan


def test_p6_structured_objective_records_constraints_authority_and_acceptance():
    objective = build_structured_objective(
        "Ship the browser benchmark",
        constraints=["code only", "do not upload markdown"],
        assumptions=["local fixture is acceptable"],
        authority=["user approved installing Chromium"],
        deadline="2026-07-11",
        acceptance_criteria=["50 cases pass"],
    )
    assert objective.requested_outcome == "Ship the browser benchmark"
    assert objective.hard_constraints() == ["code only", "do not upload markdown"]
    assert objective.assumptions[0].state == InformationState.INFERRED
    assert objective.authority == ["user approved installing Chromium"]
    assert objective.acceptance_criteria == ["50 cases pass"]


def test_p6_planner_executor_ready_steps_and_dependency_guard():
    objective = build_structured_objective("Complete P6")
    plan = plan_from_steps(objective, [
        {
            "id": "plan",
            "text": "Create dependency-aware plan",
            "role": "planner",
            "evidence_required": ["plan has checks"],
            "mutable_resources": ["core/cognitive_architecture.py"],
        },
        {
            "id": "execute",
            "text": "Implement ready step",
            "role": "executor",
            "dependencies": ["plan"],
            "risks": ["state drift"],
        },
    ])
    assert [step.step_id for step in plan.ready_steps()] == ["plan"]
    transition = execute_ready_step(plan, "plan", "tests cover the contract")
    assert transition.from_status == "pending"
    assert [step.step_id for step in plan.ready_steps()] == ["execute"]


def test_p6_verifier_repair_loop_and_pass_rate_are_independent():
    findings = [
        VerificationFinding("local file", True, "pytest passed", independent=True),
        VerificationFinding("remote state", False, "health endpoint stale", independent=True, remote_state_checked=True),
    ]
    repairs = repair_steps_from_findings(findings)
    assert len(repairs) == 1
    assert repairs[0].source_finding == "health endpoint stale"


def test_p6_uncertainty_model_distinguishes_information_states():
    assert classify_information("confirmed by test", evidence="pytest").state == InformationState.KNOWN
    assert classify_information("old snapshot", stale=True).state == InformationState.STALE
    assert classify_information("two sources disagree", conflicting=True).state == InformationState.CONFLICTING
    assert classify_information("unknown provider status").state == InformationState.UNAVAILABLE
    assert classify_information("depends on owner approval").state == InformationState.DECISION_DEPENDENT
    assert classify_information("probably safe").state == InformationState.INFERRED


def test_p6_model_routing_prefers_strong_models_for_judgment_and_efficient_for_routine():
    planning = route_model(CognitiveRole.PLANNER, "planning")
    routine = route_model(CognitiveRole.EXECUTOR, "formatting")
    high_stakes = route_model(CognitiveRole.EXECUTOR, "email_send", high_stakes=True)
    assert planning.preferred_tier == "strong"
    assert planning.fallback_tiers
    assert routine.preferred_tier == "efficient"
    assert high_stakes.preferred_tier == "strong"


def test_p6_context_package_contains_task_specific_subset():
    objective = build_structured_objective("Patch app", constraints=["preserve user files"])
    plan = plan_from_steps(objective, [
        {"id": "s1", "text": "Read files", "risks": ["missing context"]},
        {"id": "s2", "text": "Patch files", "dependencies": ["s1"], "risks": ["regression"]},
    ])
    state = CognitiveState(objective, plan)
    state.findings.append(VerificationFinding("read", True, "opened core files"))
    state.uncertainty.append(classify_information("external docs may be stale", stale=True))
    package = build_context_package(state)
    assert package.objective == "Patch app"
    assert package.constraints == ("preserve user files",)
    assert package.ready_steps == ("Read files",)
    assert package.evidence == ("opened core files",)
    assert any(item.startswith("stale:") for item in package.uncertainty)


def test_p6_parallelism_rejects_shared_mutable_resources_and_allows_independent_steps():
    objective = build_structured_objective("Parallel checks")
    conflict = plan_from_steps(objective, [
        {"id": "a", "text": "Patch A", "mutable_resources": ["app.py"]},
        {"id": "b", "text": "Patch B", "mutable_resources": ["app.py"]},
    ])
    independent = plan_from_steps(objective, [
        {"id": "a", "text": "Read A", "mutable_resources": ["a.py"]},
        {"id": "b", "text": "Read B", "mutable_resources": ["b.py"]},
    ])
    assert decide_parallelism(conflict.steps).allowed is False
    assert decide_parallelism(independent.steps).allowed is True


def test_p6_counterexample_and_stopping_policy():
    check = counterexample_check(consequential=True, alternatives=["network issue"], failure_cases=[])
    assert check.required is True
    assert stopping_policy(authority_missing=True).reason == StopReason.MISSING_AUTHORITY
    assert stopping_policy(evidence_sufficient=True).reason == StopReason.SUFFICIENT_EVIDENCE
    assert stopping_policy(attempts=2, max_attempts=2).reason == StopReason.LOW_EXPECTED_VALUE
    assert stopping_policy(attempts=0, max_attempts=2).should_stop is False


def test_task_lifecycle_carries_p6_cognitive_state_from_plan_update():
    task = create_task_frame("继续完成 P6 并验证", classify_intent("继续完成 P6 并验证"))
    update_plan(task, [
        {
            "text": "Build P6 contracts",
            "status": "doing",
            "check": "tests pass",
            "dependencies": [],
            "evidence_required": ["pytest"],
            "risks": ["regression"],
            "mutable_resources": ["core/cognitive_architecture.py"],
        }
    ])
    assert task.cognitive_state is not None
    plan = task.cognitive_state.plan
    assert plan.objective.requested_outcome == task.objective
    assert plan.steps[0].evidence_required == ["pytest", "tests pass"]
    assert plan.steps[0].risks == ["regression"]
    assert plan.steps[0].mutable_resources == ["core/cognitive_architecture.py"]
