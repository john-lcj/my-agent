"""审计日志 —— append-only 记录"agent 到底做了什么",供事后追溯与合规。

每行一条 JSON(JSONL),写到 logs/audit.log。只记关键、安全相关的字段,
**不记文件内容/密钥**(参数只摘录 path/command/to 等并截断),避免日志本身变成泄密源。
失败静默:审计绝不能阻断主流程。
"""
from __future__ import annotations

import json
import os
import time

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
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
