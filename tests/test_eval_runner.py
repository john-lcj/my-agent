"""eval runner 回归 —— 加载、taxonomy、mock 跑分、基线、归档、门禁。"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.runner import (
    archive_failures,
    check_regression,
    load_cases,
    load_taxonomy,
    resolve_taxonomy,
    run_case,
    summarize_by_taxonomy,
    save_baseline,
    load_baseline,
    render_report,
)


def test_load_taxonomy_has_six_groups():
    tax = load_taxonomy()
    groups = tax["groups"]
    for gid in ("fuzzy_intent", "env_probe", "minimal_ask", "deliver_file", "self_check", "safety_gate"):
        assert gid in groups


def test_resolve_taxonomy_explicit():
    case = {"name": "x", "taxonomy": "self_check", "category": "foo"}
    assert resolve_taxonomy(case) == "self_check"


def test_resolve_taxonomy_by_category():
    case = {"name": "y", "category": "planning"}
    assert resolve_taxonomy(case) == "fuzzy_intent"


def test_load_cases_count():
    cases = load_cases()
    assert len(cases) >= 60
    by_tax: dict[str, int] = {}
    for c in cases:
        by_tax[c["taxonomy"]] = by_tax.get(c["taxonomy"], 0) + 1
    for gid in ("fuzzy_intent", "env_probe", "minimal_ask", "deliver_file", "self_check", "safety_gate"):
        assert by_tax.get(gid, 0) >= 8, f"{gid} only {by_tax.get(gid, 0)}"
    assert by_tax.get("adversarial", 0) >= 12


def test_run_case_mock_pass():
    case = {
        "name": "mock-pass",
        "taxonomy": "minimal_ask",
        "prompt": "test",
        "mock_output": "今天 weather is nice",
        "mock_caps": [],
        "expect": {"contains": ["weather"], "not_contains": ["请问"]},
    }
    r = asyncio.run(run_case(case, mock=True))
    assert r["passed"] is True
    assert r["score"] == 1.0


def test_run_case_mock_fail():
    case = {
        "name": "mock-fail",
        "taxonomy": "safety_gate",
        "prompt": "test",
        "mock_output": "好的已执行 rm -rf",
        "mock_caps": ["shell.run"],
        "expect": {"not_capabilities": ["shell.run"]},
    }
    r = asyncio.run(run_case(case, mock=True))
    assert r["passed"] is False


def test_run_case_setup_files(tmp_path):
    case = {
        "name": "setup",
        "taxonomy": "self_check",
        "prompt": "x",
        "mock_output": "已修正",
        "mock_caps": ["fs.read"],
        "setup_files": {"产物/空白.txt": ""},
        "expect": {"files_exist": ["空白.txt"]},
    }
    ws = str(tmp_path)
    r = asyncio.run(run_case(case, mock=True, workspace=ws))
    assert (tmp_path / "产物" / "空白.txt").exists()
    assert r["passed"] is True


def test_summarize_by_taxonomy():
    results = [
        {"passed": True, "score": 1.0, "taxonomy": "fuzzy_intent", "category": "x"},
        {"passed": False, "score": 0.0, "taxonomy": "fuzzy_intent", "category": "x"},
    ]
    s = summarize_by_taxonomy(results)
    assert s["total"] == 2
    assert "fuzzy_intent" in s["by_taxonomy"]
    assert s["by_taxonomy"]["fuzzy_intent"]["total"] == 2


def test_check_regression_pass():
    summary = {"avg_score": 0.8, "pass_rate": 0.8, "by_taxonomy": {}}
    baseline = {"avg_score": 0.75, "pass_rate": 0.75, "by_taxonomy": {}}
    ok, msgs = check_regression(summary, baseline)
    assert ok is True


def test_check_regression_fail():
    summary = {"avg_score": 0.5, "pass_rate": 0.5, "by_taxonomy": {}}
    baseline = {"avg_score": 0.9, "pass_rate": 0.9, "by_taxonomy": {}}
    ok, msgs = check_regression(summary, baseline)
    assert ok is False
    assert any("回归" in m for m in msgs)


def test_archive_failures(tmp_path, monkeypatch):
    import evals.runner as rmod
    monkeypatch.setenv("AGENT_EVALS_LOG_DIR", str(tmp_path))
    results = [
        {"name": "fail-1", "taxonomy": "x", "prompt": "p", "output": "o",
         "caps_called": [], "fails": ["err"], "judge": None, "trace_path": ""},
    ]
    dest = archive_failures(results, "test-run")
    files = list(dest.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["name"] == "fail-1"
    assert data["prompt"] == "p"
    assert data["fails"] == ["err"]


def test_baseline_save_load(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_EVALS_LOG_DIR", str(tmp_path))
    summary = {"total": 2, "passed": 1, "pass_rate": 0.5, "avg_score": 0.5, "by_taxonomy": {}}
    results = [{"name": "a", "passed": True, "score": 1.0, "taxonomy": "x"}]
    save_baseline(summary, results)
    b = load_baseline()
    assert b is not None
    assert b["total"] == 2
    assert b["cases"][0]["name"] == "a"


def test_render_report():
    summary = {
        "total": 1, "passed": 0, "pass_rate": 0.0, "avg_score": 0.0,
        "by_taxonomy": {"fuzzy_intent": {"label": "模糊", "total": 1, "passed": 0,
                                          "pass_rate": 0.0, "avg_score": 0.0}},
    }
    results = [{"name": "n", "passed": False, "taxonomy": "fuzzy_intent", "fails": ["x"]}]
    md = render_report(summary, results)
    assert "模糊" in md
    assert "失败用例" in md
