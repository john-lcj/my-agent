"""评测 runner —— 加载用例、隔离工作区、驱动 Agent、打分、归档。"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml

from evals.judge import judge_quality
from evals.scoring import compare_baseline, score_case, summarize

_ROOT = Path(__file__).resolve().parent.parent
_CASES_DIR = Path(__file__).resolve().parent / "cases"
_TAXONOMY_PATH = Path(__file__).resolve().parent / "taxonomy.yaml"


def _evals_log_dir() -> Path:
    override = os.environ.get("AGENT_EVALS_LOG_DIR", "").strip()
    if override:
        return Path(override)
    return _ROOT / "logs" / "evals"


def load_taxonomy() -> dict:
    if not _TAXONOMY_PATH.exists():
        return {"groups": {}, "by_category": {}, "by_name": {}}
    data = yaml.safe_load(_TAXONOMY_PATH.read_text(encoding="utf-8")) or {}
    return {
        "groups": data.get("groups") or {},
        "by_category": data.get("by_category") or {},
        "by_name": data.get("by_name") or {},
    }


def resolve_taxonomy(case: dict, tax: Optional[dict] = None) -> str:
    if case.get("taxonomy"):
        return str(case["taxonomy"])
    tax = tax or load_taxonomy()
    name = case.get("name", "")
    if name in tax["by_name"]:
        return tax["by_name"][name]
    cat = case.get("category", "")
    if cat in tax["by_category"]:
        return tax["by_category"][cat]
    return cat or "未分类"


def load_cases(category: Optional[str] = None) -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    tax = load_taxonomy()
    for path in sorted(_CASES_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            continue
        for c in raw:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            key = c["name"]
            if key in seen:
                continue
            seen.add(key)
            item = dict(c)
            item["taxonomy"] = resolve_taxonomy(item, tax)
            item["_source"] = path.name
            if category and item["taxonomy"] != category:
                continue
            cases.append(item)
    return cases


def _collect_files_text(workspace: str) -> str:
    parts: list[str] = []
    ws = Path(workspace)
    for base in (ws / "产物", ws):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".xlsx", ".pdf"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = p.relative_to(ws)
            parts.append(f"--- {rel} ---\n{text[:8000]}")
    return "\n\n".join(parts)


def _case_score(passed: bool, judge: Optional[dict]) -> float:
    if judge and judge.get("score") is not None:
        return float(judge["score"]) / 10.0
    return 1.0 if passed else 0.0


async def _auto_confirm(call, decision, reason=""):
    return True


async def run_case(
    case: dict,
    *,
    mock: bool = False,
    workspace: Optional[str] = None,
) -> dict:
    ws = workspace
    cleanup = False
    if not ws:
        ws = tempfile.mkdtemp(prefix="captain-eval-")
        cleanup = True
    os.makedirs(os.path.join(ws, "产物"), exist_ok=True)

    for rel, content in (case.get("setup_files") or {}).items():
        fp = Path(ws) / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    caps_called: list[str] = []
    output = ""
    full_output = ""   # 全部 assistant 回复拼接:拒绝/说明可能在早轮,判分要看全对话
    error = ""
    trace_path = ""

    old_ws = os.environ.get("AGENT_WORKSPACE_ROOT")
    old_log = os.environ.get("AGENT_LOG_DIR")
    os.environ["AGENT_WORKSPACE_ROOT"] = ws
    os.environ["AGENT_LOG_DIR"] = os.path.join(ws, "logs")
    os.makedirs(os.environ["AGENT_LOG_DIR"], exist_ok=True)

    try:
        if mock:
            output = case.get("mock_output", "")
            caps_called = list(case.get("mock_caps") or [])
        else:
            from core.bootstrap import build_agent_bundle
            from core.types import EventType, Identity

            identity = Identity(subject_id="eval", agent_name="main", channel="eval")
            bundle = build_agent_bundle(
                identity,
                profile="interactive",
                with_rollback=False,
                max_steps=case.get("max_steps") or 40,
            )
            if case.get("mode") == "coworker":
                bundle.ctx.coworker = True
                bundle.ctx.task_auto_approve = True

            def _on_event(ev):
                if ev.type == EventType.CAPABILITY_RESULT:
                    payload = ev.payload or {}
                    if payload.get("ok") and payload.get("name"):
                        caps_called.append(payload["name"])

            bundle.bus.subscribe(_on_event)
            try:
                output = await bundle.agent.run(case["prompt"], bundle.ctx, _auto_confirm)
                try:
                    from core.types import Role
                    texts = [
                        m.content for m in (bundle.ctx.messages or [])
                        if getattr(m, "role", None) == Role.ASSISTANT
                        and (m.content or "").strip()
                        and not getattr(m, "tool_calls", None)
                    ]
                    full_output = "\n\n".join(texts)
                except Exception:
                    full_output = ""
                trace_id = getattr(bundle.agent, "last_trace_id", "") or ""
                if trace_id:
                    tp = Path(os.environ["AGENT_LOG_DIR"]) / "transcripts" / f"{trace_id}.md"
                    if tp.exists():
                        trace_path = str(tp)
            except Exception as e:
                error = str(e)
                output = output or f"[runner error] {e}"
    finally:
        if old_ws is None:
            os.environ.pop("AGENT_WORKSPACE_ROOT", None)
        else:
            os.environ["AGENT_WORKSPACE_ROOT"] = old_ws
        if old_log is None:
            os.environ.pop("AGENT_LOG_DIR", None)
        else:
            os.environ["AGENT_LOG_DIR"] = old_log

    files_text = _collect_files_text(ws)
    expect = case.get("expect") or {}
    # 判分用全对话文本(拒绝/声明可能出现在早轮回复);mock 或取不到时回退最终回复
    score_text = full_output if len(full_output) > len(output or "") else (output or "")
    passed, fails = score_case(score_text, caps_called, expect, files_text=files_text)

    judge_result = None
    if expect.get("judge"):
        judge_result = await judge_quality(
            case.get("prompt", ""),
            output + ("\n\n" + files_text[:2000] if files_text else ""),
            expect["judge"],
            int(expect.get("judge_threshold") or 6),
        )
        if judge_result is not None and not judge_result.get("passed"):
            passed = False
            fails = list(fails) + [f"judge:{judge_result.get('comment', '')}"]

    result = {
        "name": case["name"],
        "category": case.get("category", ""),
        "taxonomy": case.get("taxonomy") or resolve_taxonomy(case),
        "prompt": case.get("prompt", ""),
        "passed": passed,
        "score": _case_score(passed, judge_result),
        "fails": fails,
        "output": (output or "")[:4000],
        "caps_called": caps_called,
        "judge": judge_result,
        "trace_path": trace_path,
        "workspace": ws if not cleanup else "",
        "error": error,
    }
    if cleanup:
        shutil.rmtree(ws, ignore_errors=True)
    return result


async def run_all(
    cases: list[dict],
    *,
    mock: bool = False,
    on_progress: Optional[Callable[[int, int, dict], None]] = None,
) -> list[dict]:
    results = []
    total = len(cases)
    for i, case in enumerate(cases, 1):
        r = await run_case(case, mock=mock)
        results.append(r)
        if on_progress:
            on_progress(i, total, r)
    return results


def summarize_by_taxonomy(results: list[dict], tax: Optional[dict] = None) -> dict:
    tax = tax or load_taxonomy()
    groups = tax.get("groups") or {}
    by: dict[str, dict] = {}
    for gid, meta in groups.items():
        by[gid] = {
            "label": meta.get("label", gid),
            "total": 0,
            "passed": 0,
            "pass_rate": 0.0,
            "avg_score": 0.0,
            "_scores": [],
        }
    for r in results:
        tid = r.get("taxonomy") or "未分类"
        if tid not in by:
            by[tid] = {"label": tid, "total": 0, "passed": 0, "pass_rate": 0.0,
                       "avg_score": 0.0, "_scores": []}
        by[tid]["total"] += 1
        if r.get("passed"):
            by[tid]["passed"] += 1
        by[tid]["_scores"].append(float(r.get("score") or 0))
    for g in by.values():
        t = g["total"]
        g["pass_rate"] = round(g["passed"] / t, 3) if t else 0.0
        scores = g.pop("_scores", [])
        g["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
    overall = summarize(results)
    scores = [float(r.get("score") or 0) for r in results]
    overall["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
    overall["by_taxonomy"] = by
    return overall


def _baseline_path() -> Path:
    return _evals_log_dir() / "baseline.json"


def _history_path() -> Path:
    return _evals_log_dir() / "history.jsonl"


def load_baseline() -> Optional[dict]:
    p = _baseline_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_baseline(summary: dict, results: list[dict]) -> None:
    _evals_log_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "total": summary.get("total", 0),
        "passed": summary.get("passed", 0),
        "pass_rate": summary.get("pass_rate", 0),
        "avg_score": summary.get("avg_score", 0),
        "by_taxonomy": summary.get("by_taxonomy", {}),
        "cases": [
            {"name": r["name"], "passed": r["passed"], "score": r.get("score", 0),
             "taxonomy": r.get("taxonomy", "")}
            for r in results
        ],
    }
    _baseline_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(summary: dict) -> None:
    _evals_log_dir().mkdir(parents=True, exist_ok=True)
    row = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "pass_rate": summary.get("pass_rate"),
        "avg_score": summary.get("avg_score"),
        "by_taxonomy": {
            k: {"pass_rate": v.get("pass_rate"), "avg_score": v.get("avg_score")}
            for k, v in (summary.get("by_taxonomy") or {}).items()
        },
    }
    with _history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def check_regression(summary: dict, baseline: Optional[dict], threshold: float = 0.05) -> tuple[bool, list[str]]:
    if not baseline:
        return True, ["无基线，跳过回归门禁"]
    msgs: list[str] = []
    ok = True
    cur = float(summary.get("avg_score") or summary.get("pass_rate") or 0)
    base = float(baseline.get("avg_score") or baseline.get("pass_rate") or 0)
    if base > 0 and (base - cur) / base > threshold:
        ok = False
        msgs.append(f"总分/均分回归: {cur:.3f} vs 基线 {base:.3f} (跌>{threshold*100:.0f}%)")

    cur_tax = summary.get("by_taxonomy") or {}
    base_tax = baseline.get("by_taxonomy") or {}
    for tid, bg in base_tax.items():
        cg = cur_tax.get(tid) or {}
        bsc = float(bg.get("avg_score") or bg.get("pass_rate") or 0)
        csc = float(cg.get("avg_score") or cg.get("pass_rate") or 0)
        if bsc > 0 and (bsc - csc) / bsc > threshold:
            ok = False
            label = bg.get("label") or tid
            msgs.append(f"[{label}] 回归: {csc:.3f} vs {bsc:.3f}")
    if ok:
        msgs.append("回归门禁通过")
    return ok, msgs


def archive_failures(results: list[dict], run_id: str) -> Path:
    fails = [r for r in results if not r.get("passed")]
    dest = _evals_log_dir() / "failures" / run_id
    if not fails:
        dest.mkdir(parents=True, exist_ok=True)
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    for r in fails:
        fp = dest / f"{_safe_name(r['name'])}.json"
        fp.write_text(json.dumps({
            "name": r["name"],
            "taxonomy": r.get("taxonomy"),
            "prompt": r.get("prompt"),
            "output": r.get("output"),
            "caps_called": r.get("caps_called"),
            "fails": r.get("fails"),
            "judge_reason": (r.get("judge") or {}).get("comment"),
            "trace_path": r.get("trace_path"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", s)[:80]


def render_report(
    summary: dict,
    results: list[dict],
    *,
    baseline: Optional[dict] = None,
    regression_msgs: Optional[list[str]] = None,
    failure_dir: Optional[Path] = None,
) -> str:
    lines = [
        "# Captain Eval Report",
        "",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"总计: {summary.get('passed')}/{summary.get('total')} 通过 "
        f"({summary.get('pass_rate', 0)*100:.1f}%)",
        f"均分: {summary.get('avg_score', 0):.3f}",
        "",
    ]
    if baseline:
        bpr = baseline.get("pass_rate", 0)
        diff = summary.get("pass_rate", 0) - bpr
        sign = "+" if diff >= 0 else ""
        lines.append(f"基线通过率: {bpr*100:.1f}% ({sign}{diff*100:.1f}%)")
        lines.append("")
    if regression_msgs:
        lines.append("## 回归门禁")
        for m in regression_msgs:
            lines.append(f"- {m}")
        lines.append("")

    lines.append("## 六类能力")
    for tid, g in (summary.get("by_taxonomy") or {}).items():
        if tid == "adversarial":
            continue
        label = g.get("label", tid)
        t, p = g.get("total", 0), g.get("passed", 0)
        pr = g.get("pass_rate", 0) * 100
        asc = g.get("avg_score", 0)
        diff_s = ""
        if baseline and tid in (baseline.get("by_taxonomy") or {}):
            bg = baseline["by_taxonomy"][tid]
            bsc = bg.get("avg_score") or bg.get("pass_rate") or 0
            csc = g.get("avg_score") or g.get("pass_rate") or 0
            d = csc - bsc
            diff_s = f" ({'+' if d >= 0 else ''}{d:.3f} vs基线)"
        lines.append(f"- **{label}** (`{tid}`): {p}/{t} ({pr:.0f}%) 均分 {asc:.3f}{diff_s}")
    lines.append("")

    adv = (summary.get("by_taxonomy") or {}).get("adversarial")
    if adv and adv.get("total"):
        lines.append("## 对抗用例")
        lines.append(f"- {adv.get('passed')}/{adv.get('total')} 通过")
        lines.append("")

    fails = [r for r in results if not r.get("passed")]
    if fails:
        lines.append("## 失败用例")
        for r in fails:
            lines.append(f"- {r['name']} [{r.get('taxonomy')}]: {'; '.join(r.get('fails') or [])[:200]}")
        if failure_dir:
            lines.append(f"\n归档目录: `{failure_dir}`")
    else:
        lines.append("## 失败用例\n无")
    return "\n".join(lines) + "\n"


def compare_case_regression(current: list[dict], baseline: Optional[dict]) -> dict:
    base_cases = {c["name"]: c for c in (baseline or {}).get("cases", [])}
    return compare_baseline(
        [{"name": r["name"], "passed": r["passed"]} for r in current],
        [{"name": n, "passed": c.get("passed")} for n, c in base_cases.items()],
    )
