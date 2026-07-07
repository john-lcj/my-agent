"""任务自评 —— 会话结束 1–5 分,周汇总。"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict


def _path(log_dir: str) -> str:
    return os.path.join(log_dir, "task_ratings.jsonl")


def record_rating(log_dir: str, session_id: str, score: int, note: str = "") -> None:
    os.makedirs(log_dir, exist_ok=True)
    rec = {
        "ts": time.time(),
        "session_id": (session_id or "")[:40],
        "score": max(1, min(5, int(score))),
        "note": (note or "")[:200],
    }
    with open(_path(log_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def rate_session_with_llm(messages: list, llm=None) -> tuple[int, str]:
    """LLM 会话自评 1–5;失败则启发式。"""
    if llm is None:
        return _heuristic_rating(messages)
    snippet = []
    for m in messages[-12:]:
        role = getattr(m, "role", None)
        c = (getattr(m, "content", None) or "")[:300]
        if c:
            snippet.append(f"{role}: {c}")
    if not snippet:
        return 4, "会话过短"
    prompt = (
        "你是质量评审。根据以下对话片段,给本次任务完成质量打 1–5 分(5最好),"
        "并一句中文原因。只回复 JSON:{\"score\":N,\"note\":\"...\"}\n\n"
        + "\n".join(snippet[-8:])
    )
    try:
        step = await llm.next_step([{"role": "user", "content": prompt}], [])
        text = (step.text or "").strip()
        if "{" in text:
            data = json.loads(text[text.index("{"):text.rindex("}") + 1])
            s = int(data.get("score", 4))
            return max(1, min(5, s)), str(data.get("note", ""))[:200]
    except Exception:
        pass
    return _heuristic_rating(messages)


def _heuristic_rating(messages: list) -> tuple[int, str]:
    score, note = 4, "会话完成"
    bad = 0
    for m in messages[-40:]:
        c = (getattr(m, "content", None) or "").lower()
        if any(x in c for x in ("blocked", "traceback", "失败", "❌", "error:", "门禁未通过")):
            bad += 1
    if bad >= 3:
        return 2, f"多处异常信号({bad})"
    if bad >= 1:
        return 3, f"存在异常信号({bad})"
    if len(messages) >= 8:
        return 5, "多轮完成无异常"
    return score, note


def weekly_summary(log_dir: str, days: float = 7.0) -> dict:
    path = _path(log_dir)
    if not os.path.isfile(path):
        return {"count": 0, "avg": 0.0, "by_day": {}}
    cutoff = time.time() - days * 86400
    scores: list[int] = []
    by_day: dict[str, list[int]] = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            if float(rec.get("ts") or 0) < cutoff:
                continue
            s = int(rec.get("score") or 0)
            if 1 <= s <= 5:
                scores.append(s)
                day = time.strftime("%Y-%m-%d", time.localtime(rec["ts"]))
                by_day[day].append(s)
    avg = sum(scores) / len(scores) if scores else 0.0
    return {
        "count": len(scores),
        "avg": round(avg, 2),
        "by_day": {d: round(sum(v) / len(v), 2) for d, v in sorted(by_day.items())},
    }
