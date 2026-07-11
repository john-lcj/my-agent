import pytest


def test_real_browser_benchmark_runner_completes_when_playwright_is_available():
    pytest.importorskip("playwright.sync_api")
    from browser_runtime.benchmark_runner import run_benchmark

    summary = run_benchmark()
    assert summary["total"] == 50
    assert summary["failed"] == 0
    assert summary["unattended_total"] == 45
    assert summary["unattended_success_rate"] == 1.0
    assert summary["supervised_total"] == 5
    assert summary["supervised_success_rate"] == 1.0
