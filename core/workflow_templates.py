"""内置生命周期工作流模板 —— 目标→计划→执行→自检→返修→汇报。"""
from __future__ import annotations

import re

WORKFLOW_TEMPLATES = [
    {
        "name": "文档交付",
        "slug": "wf_deliver_doc",
        "prompt": (
            "【工作流:文档交付】\n"
            "1) 用 plan.update 列出:理解需求→写文档→回读校验→汇报\n"
            "2) 产物写到 产物/ 目录\n"
            "3) 汇报时引用文件中的关键片段作为证据"
        ),
        "verifications": [{"kind": "read_file", "target": "产物/"}],
    },
    {
        "name": "代码改动",
        "slug": "wf_code_change",
        "prompt": (
            "【工作流:代码改动】\n"
            "1) plan.update 列出改动点与测试方式\n"
            "2) 改完后跑最小测试\n"
            "3) 汇报附 pytest 原始输出"
        ),
        "verifications": [{"kind": "run_test", "target": "python3 -m pytest -q tests/test_regression.py"}],
    },
    {
        "name": "调研报告",
        "slug": "wf_research_report",
        "prompt": (
            "【工作流:调研报告】\n"
            "1) 先检索/读资料再写报告\n"
            "2) 报告存 产物/ 并回读检查结构(背景/发现/建议)\n"
            "3) 汇报附文件摘要"
        ),
        "verifications": [{"kind": "read_file", "target": "产物/"}],
    },
]


def verification_marker(verifications: list[dict] | None) -> str:
    if not verifications:
        return ""
    parts = [f"{v.get('kind', '')}:{v.get('target', '')}" for v in verifications if v.get("kind")]
    if not parts:
        return ""
    return "\n【自动验证项】" + "|".join(parts)


def prompt_with_verifications(template: dict) -> str:
    return (template.get("prompt") or "") + verification_marker(template.get("verifications"))


def apply_workflow_verifications(task_frame, user_text: str) -> None:
    """从用户消息解析【自动验证项】并挂到 TaskFrame(S20)。"""
    m = re.search(r"【自动验证项】([^\n]+)", user_text or "")
    if not m or task_frame is None:
        return
    from core.verification import append_verification
    for part in m.group(1).split("|"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        kind, target = part.split(":", 1)
        append_verification(task_frame, kind.strip(), target.strip())


def get_template_by_slug(slug: str) -> dict | None:
    for t in WORKFLOW_TEMPLATES:
        if t.get("slug") == slug:
            return t
    return None


def seed_workflow_templates(template_store) -> int:
    n = 0
    for t in WORKFLOW_TEMPLATES:
        try:
            existing = [x for x in template_store.list() if x.get("title") == t["name"]]
            if existing:
                continue
            template_store.save(
                t["name"], prompt_with_verifications(t),
                category="workflow," + t["slug"], tid=t["slug"],
            )
            n += 1
        except Exception:
            pass
    return n
