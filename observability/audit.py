"""审计日志 —— append-only 记录"agent 到底做了什么",供事后追溯与合规。

每行一条 JSON(JSONL),写到 logs/audit.log。只记关键、安全相关的字段,
**不记文件内容/密钥**(参数只摘录 path/command/to 等并截断),避免日志本身变成泄密源。
失败静默:审计绝不能阻断主流程。
"""
from __future__ import annotations

import json
import os
import time
import hashlib

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


def _previous_hash(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as f:
            lines = f.read().splitlines()
        return json.loads(lines[-1]).get("hash", "") if lines else ""
    except Exception:
        return ""


def verify_chain(path: str | None = None) -> bool:
    target = path or _audit_path()
    previous = ""
    try:
        with open(target, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                digest = record.pop("hash", "")
                # Pre-P1 records were append-only but unchained. They form a
                # legacy prefix; once a chain record appears, every following
                # record must be chained.
                if not digest and not previous:
                    continue
                if not digest:
                    return False
                if record.get("prev_hash", "") != previous:
                    return False
                encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if digest != hashlib.sha256((previous + encoded).encode()).hexdigest():
                    return False
                previous = digest
    except FileNotFoundError:
        return True
    except Exception:
        return False
    return True


def audit(*, trace_id: str = "", agent: str = "", capability: str = "",
          args: dict | None = None, decision: str = "", ok: bool | None = None,
          detail: str = "", authority: str = "owner", evidence: str = "") -> None:
    """追加一条审计记录。任何异常都吞掉(审计不能拖垮主流程)。"""
    try:
        path = _audit_path()
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "trace": trace_id,
            "agent": agent,
            "cap": capability,
            "args": _summarize_args(args or {}),
            "decision": decision,
            "ok": ok,
            "detail": str(detail)[:200],
            "authority": authority,
            "evidence": str(evidence)[:200],
            "prev_hash": _previous_hash(path),
        }
        encoded = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rec["hash"] = hashlib.sha256((rec["prev_hash"] + encoded).encode()).hexdigest()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        append_text(path, json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
