"""审计日志 —— append-only 记录"agent 到底做了什么",供事后追溯与合规。

每行一条 JSON(JSONL),写到 logs/audit.log。只记关键、安全相关的字段,
**不记文件内容/密钥**(参数只摘录 path/command/to 等并截断),避免日志本身变成泄密源。
失败静默:审计绝不能阻断主流程。
"""
from __future__ import annotations

import json
import os
import time

from observability.log_rotation import append_text

# 只摘录这些参数键(安全相关),其余忽略;值截断到 200 字符。
_ARG_KEYS = ("path", "command", "to", "group_id", "user_id", "query", "agent", "task", "url")


def _audit_path() -> str:
    try:
        from config import Config
        base = Config.LOG_DIR
    except Exception:
        base = "logs"
    return os.path.join(base, "audit.log")


def _summarize_args(args: dict) -> dict:
    out = {}
    for k in _ARG_KEYS:
        if k in (args or {}):
            out[k] = str(args[k])[:200]
    return out


def read_recent(limit: int = 100, *, capability: str = "", agent: str = "",
                decision: str = "", ok: bool | None = None) -> list[dict]:
    """读最近 N 条审计记录(倒序,最新在前),可选按 cap/agent/decision/ok 筛选。"""
    path = _audit_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    cap_f = (capability or "").strip().lower()
    agent_f = (agent or "").strip().lower()
    decision_f = (decision or "").strip().lower()
    out: list[dict] = []
    for ln in reversed(lines):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if cap_f and cap_f not in str(rec.get("cap") or "").lower():
            continue
        if agent_f and agent_f not in str(rec.get("agent") or "").lower():
            continue
        if decision_f and decision_f not in str(rec.get("decision") or "").lower():
            continue
        if ok is not None and rec.get("ok") is not ok:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def audit(*, trace_id: str = "", agent: str = "", capability: str = "",
          args: dict | None = None, decision: str = "", ok: bool | None = None,
          detail: str = "") -> None:
    """追加一条审计记录。任何异常都吞掉(审计不能拖垮主流程)。"""
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "trace": trace_id,
            "agent": agent,
            "cap": capability,
            "args": _summarize_args(args or {}),
            "decision": decision,
            "ok": ok,
            "detail": str(detail)[:200],
        }
        path = _audit_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        append_text(path, json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
