from __future__ import annotations

from core.p6_benchmark import run_p6_long_horizon_benchmark


def test_p6_long_horizon_acceptance_benchmark_meets_release_gates():
    report = run_p6_long_horizon_benchmark()
    assert report.meaningful_steps == 50
    assert report.constraint_retention_rate == 1.0
    assert report.false_completion_rate < 0.02
    assert report.seeded_defect_capture_rate >= 0.95
    assert report.fallback_contract_preserved
    assert report.parallelism_safe
    assert report.stopping_policy_safe
    assert report.passed
