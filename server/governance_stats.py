"""治理统计 —— 从 trace.jsonl 聚合规则命中次数。"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Any

# 复用本会话此前授权,无需再次询问
REUSE_RULES = frozenset({"task:auto", "grant:capability", "grant", "auto", "memory:auto"})

RULE_LABELS_ZH: dict[str, str] = {
    "auto": "自动放行",
    "confirm:fs.write": "写文件",
    "confirm:gui": "控制电脑",
    "confirm:payment": "花钱/支付",
    "memory:auto": "记住偏好/事实",
    "memory:block_unattended": "无人值守禁写记忆",
    "risk:forbidden": "禁止能力",
    "task:auto": "本任务已授权",
    "grant:capability": "能力已授权",
    "grant": "路径已授权",
    "(none)": "未分类",
}

DECISION_LABELS_ZH: dict[str, str] = {
    "allow": "放行",
    "ask": "需确认",
    "block": "拒绝",
    "unknown": "未知",
}


def rule_label_zh(rule: str) -> str:
    if rule in RULE_LABELS_ZH:
        return RULE_LABELS_ZH[rule]
    if rule.startswith("forbidden_path:"):
        return "敏感路径硬边界"
    if rule.startswith("mode:"):
        return "治理档位自动放行"
    return rule


def load_stats(trace_path: str, days: float = 7.0) -> dict[str, Any]:
    cutoff = time.time() - days * 86400
    by_rule: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total = 0
    allow = 0
    ask = 0
    block = 0
    reuse = 0

    if not os.path.isfile(trace_path):
        return _empty_stats(days)

    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "governance_decision":
                continue
            if row.get("ts", 0) < cutoff:
                continue
            payload = row.get("payload") or {}
            rule = payload.get("rule") or "(none)"
            decision = payload.get("decision") or "unknown"
            by_rule[rule][decision] += 1
            total += 1
            if decision == "allow":
                allow += 1
            elif decision == "ask":
                ask += 1
            elif decision == "block":
                block += 1
            if rule in REUSE_RULES:
                reuse += 1

    hit_rate = (allow / total) if total else 0.0
    reuse_rate = (reuse / total) if total else 0.0

    rows = []
    for rule, counts in sorted(by_rule.items(), key=lambda x: -sum(x[1].values())):
        rows.append({
            "rule": rule,
            "rule_label": rule_label_zh(rule),
            "counts": dict(counts),
        })

    return {
        "days": days,
        "total": total,
        "summary": {
            "allow": allow,
            "ask": ask,
            "block": block,
            "reuse": reuse,
            "hit_rate": round(hit_rate, 4),
            "reuse_rate": round(reuse_rate, 4),
        },
        "by_rule": dict(by_rule),
        "rows": rows,
        "labels": {
            "rules": RULE_LABELS_ZH,
            "decisions": DECISION_LABELS_ZH,
        },
    }


def _empty_stats(days: float) -> dict[str, Any]:
    return {
        "days": days,
        "total": 0,
        "summary": {
            "allow": 0,
            "ask": 0,
            "block": 0,
            "reuse": 0,
            "hit_rate": 0.0,
            "reuse_rate": 0.0,
        },
        "by_rule": {},
        "rows": [],
        "labels": {
            "rules": RULE_LABELS_ZH,
            "decisions": DECISION_LABELS_ZH,
        },
    }
