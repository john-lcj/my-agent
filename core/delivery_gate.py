"""统一交付门禁 —— 合并 lifecycle final_gate 与文件引用校验(S18/S19)。"""
from __future__ import annotations

import os
import re

from core.task_lifecycle import PHASE_REPAIR, TaskFrame, final_gate


def referenced_files(text: str) -> list[tuple[str, str | None]]:
    """从回复抽出引用文件 → (原始写法, 绝对路径或 None)。"""
    ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for c in re.findall(
        r"[\w一-鿿./_-]+\.(?:md|html|htm|pdf|docx|xlsx|xls|csv|pptx|png|jpg|jpeg|json|txt)",
        text or "",
    ):
        c = c.strip().lstrip("./")
        if not c or " " in c or c in seen:
            continue
        seen.add(c)
        cands = [c if os.path.isabs(c) else os.path.join(ws, c),
                 os.path.join(ws, "产物", os.path.basename(c))]
        full = next((p for p in cands if os.path.exists(p)), None)
        out.append((c, full))
    return out


def delivery_reference_gate(task: str, text: str) -> str:
    """文件存在性 + 空文件/公众号结构校验。返回非空=打回。"""
    if not text:
        return ""
    refs = referenced_files(text)
    missing = [c for c, f in refs if f is None]
    if missing:
        return (
            "[交付校验] 你声称已交付,但这些文件在工作区里并不存在:"
            + "、".join(missing[:5])
            + "。请真正写到 产物/ 目录(fs.write/对应技能),写完回读确认;做不到就如实说缺口,绝不谎报完成。"
        )
    problems: list[str] = []
    is_wechat = any(k in (task or "") for k in ("公众号", "推文", "微信文章"))
    for c, f in refs:
        if f is None:
            continue
        try:
            size = os.path.getsize(f)
        except OSError:
            continue
        if size < 20 and not f.lower().endswith((".png", ".jpg", ".jpeg")):
            problems.append(f"{c} 几乎是空的({size} 字节),不像真交付了内容")
            continue
        if is_wechat and f.lower().endswith(".md"):
            try:
                head = open(f, encoding="utf-8", errors="ignore").read(3000)
            except OSError:
                head = ""
            if "<section" not in head and "style=" not in head and "<p" not in head:
                problems.append(f"{c} 还是纯 Markdown;公众号需要内联样式 HTML,请用 wechat.format 生成后再交付")
    if problems:
        return "[交付校验] " + ";".join(problems[:5]) + "。请补正后再给结论。"
    return ""


def unified_final_gate(task: TaskFrame, user_text: str, final_text: str) -> str:
    """Chat/Cowork 共用:引用校验 → lifecycle(verification/repair≤2)。"""
    exec_roles = {"executor", "researcher"}
    if task.role in exec_roles or task.verification_items:
        ref = delivery_reference_gate(user_text, final_text)
        if ref:
            task.phase = PHASE_REPAIR
            task.repair_count += 1
            if task.repair_count > task.max_repairs:
                return ""
            return ref
    return final_gate(task, final_text)
