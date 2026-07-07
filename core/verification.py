"""交付自检 —— 回读文件 / 跑测试 / 证据入回复。"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Verification:
    kind: str
    target: str = ""
    status: str = "pending"
    evidence: str = ""


def append_verification(frame: Any, kind: str, target: str = "") -> None:
    if frame is None:
        return
    items = getattr(frame, "verification_items", None)
    if items is None:
        frame.verification_items = []
        items = frame.verification_items
    for v in items:
        if v.kind == kind and v.target == target and v.status == "pending":
            return
    items.append(Verification(kind=kind, target=target))


def _ws_root() -> str:
    return os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()


def _resolve_path(target: str) -> str:
    t = (target or "").strip()
    if not t:
        return ""
    if os.path.isabs(t):
        return t
    root = _ws_root()
    for c in (os.path.join(root, t), os.path.join(root, "产物", os.path.basename(t))):
        if os.path.exists(c):
            return c
    return os.path.join(root, t)


def run_verification(v: Verification) -> Verification:
    try:
        if v.kind == "read_file":
            path = _resolve_path(v.target)
            if not os.path.isfile(path):
                v.status = "fail"
                v.evidence = f"文件不存在: {v.target}"
                return v
            text = open(path, encoding="utf-8", errors="ignore").read(1500)
            v.status = "pass"
            v.evidence = text[:800]
            return v
        if v.kind == "run_test":
            cmd = v.target or "python3 -m pytest -q tests/test_regression.py"
            r = subprocess.run(
                cmd, shell=True, cwd=_ws_root(),
                capture_output=True, text=True, timeout=120,
            )
            out = (r.stdout or "") + (r.stderr or "")
            v.evidence = out[-1500:]
            v.status = "pass" if r.returncode == 0 else "fail"
            return v
        if v.kind == "check_link":
            path = _resolve_path(v.target)
            if path.lower().endswith((".html", ".htm")) and os.path.isfile(path):
                html = open(path, encoding="utf-8", errors="ignore").read(8000)
                hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
                v.evidence = f"找到 {len(hrefs)} 个链接"
                v.status = "pass"
                return v
            v.status = "fail"
            v.evidence = "非 HTML 或文件不存在"
            return v
        if v.kind == "visual_check":
            from core.visual_qa import check_artifact_layout
            path = _resolve_path(v.target)
            r = check_artifact_layout(path)
            v.evidence = r.notes + (";" + ";".join(r.issues or []) if r.issues else "")
            v.status = "pass" if r.ok else "fail"
            return v
        if v.kind == "evidence_in_reply":
            v.status = "pending"
            return v
    except Exception as e:
        v.status = "fail"
        v.evidence = str(e)[:300]
    return v


def run_verifications(frame: Any) -> tuple[bool, list[Verification]]:
    verifications: list[Verification] = list(getattr(frame, "verification_items", None) or [])
    if not verifications:
        return True, verifications
    ok = True
    for v in verifications:
        if v.status == "pass" or v.kind == "evidence_in_reply":
            continue
        run_verification(v)
        if v.status != "pass":
            ok = False
    frame.verification_items = verifications
    return ok, verifications


def evidence_block(verifications: list[Verification]) -> str:
    parts = []
    for v in verifications:
        if v.evidence:
            parts.append(f"[{v.kind}:{v.target}] {v.evidence[:400]}")
    return "\n".join(parts)


def gate_evidence_in_reply(final_text: str, verifications: list[Verification]) -> str:
    """执行型回复须含 verification 证据片段。"""
    if not verifications:
        return ""
    block = evidence_block(verifications)
    if not block:
        return ""
    text = final_text or ""
    for v in verifications:
        if v.evidence and v.evidence[:40] in text:
            return ""
        if v.evidence and any(line[:30] in text for line in v.evidence.splitlines() if len(line) > 8):
            return ""
    return "[生命周期自检] 最终回复须附上验证证据(文件回读片段或命令原始输出),请补充后再汇报。"
