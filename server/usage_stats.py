"""Token 用量统计 —— 从 trace.jsonl 聚合各次任务的 tokens 与费用。"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

_TOKENS_RE = re.compile(r"tokens=([\d,]+)")
_COST_RE = re.compile(r"cost=\$([\d.]+)")


def _parse_budget(payload: dict) -> tuple[int, float]:
    detail = payload.get("budget_detail")
    if isinstance(detail, dict):
        tokens = int(detail.get("tokens") or 0)
        cost = float(detail.get("cost_usd") or 0.0)
        return tokens, cost
    raw = payload.get("budget")
    if not raw:
        return 0, 0.0
    if isinstance(raw, dict):
        return int(raw.get("tokens") or 0), float(raw.get("cost_usd") or 0.0)
    text = str(raw)
    tokens = 0
    cost = 0.0
    m = _TOKENS_RE.search(text)
    if m:
        tokens = int(m.group(1).replace(",", ""))
    m = _COST_RE.search(text)
    if m:
        cost = float(m.group(1))
    return tokens, cost


def load_usage(trace_path: str, days: float = 30.0) -> dict[str, Any]:
    cutoff = time.time() - days * 86400
    per_trace: dict[str, dict[str, Any]] = {}

    if not os.path.isfile(trace_path):
        return {
            "days": days,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "tasks": 0,
            "by_day": [],
        }

    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "assistant_message":
                continue
            ts = float(row.get("ts") or 0)
            if ts < cutoff:
                continue
            payload = row.get("payload") or {}
            tokens, cost = _parse_budget(payload)
            if tokens <= 0 and cost <= 0:
                continue
            trace_id = row.get("trace_id") or f"row:{ts}"
            prev = per_trace.get(trace_id)
            if prev is None or ts >= prev["ts"]:
                per_trace[trace_id] = {"ts": ts, "tokens": tokens, "cost_usd": cost}

    by_day: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tokens": 0, "cost_usd": 0.0, "tasks": 0}
    )
    total_tokens = 0
    total_cost = 0.0
    for item in per_trace.values():
        total_tokens += item["tokens"]
        total_cost += item["cost_usd"]
        day = datetime.fromtimestamp(item["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[day]["tokens"] += item["tokens"]
        by_day[day]["cost_usd"] += item["cost_usd"]
        by_day[day]["tasks"] += 1

    days_sorted = sorted(by_day.keys(), reverse=True)
    by_day_list = [
        {
            "date": d,
            "tokens": int(by_day[d]["tokens"]),
            "cost_usd": round(by_day[d]["cost_usd"], 5),
            "tasks": int(by_day[d]["tasks"]),
        }
        for d in days_sorted
    ]

    return {
        "days": days,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 5),
        "tasks": len(per_trace),
        "by_day": by_day_list,
    }
