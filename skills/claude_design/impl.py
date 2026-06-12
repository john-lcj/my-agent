"""claude_design: 设计流程规范（guidance skill，不绑定专家，斜杠显式调用）。"""
from __future__ import annotations

import os
import sys

from core.types import CapabilityResult

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_DIR))
from _guidance import cap, read_skill_body, slice_between  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "overview | workflow | variants | verify | anti_slop | full",
            "default": "overview",
        },
        "brief": {"type": "string", "description": "可选：当前设计任务简述"},
    },
}

_OVERVIEW = """【claude_design 设计流程摘要】
1. 理解 brief（受众、交付物、约束）
2. 收集上下文（品牌、截图、repo、tokens）
3. 为本 artifact 定义设计系统（色/字/间距/圆角/动效）
4. 选格式：静态对比板 / 可点原型 / HTML deck / 组件实验室
5. 构建：默认单文件 HTML（内联 CSS/JS），重大改版保留 v2/v3
6. 验证：文件存在、语法、浏览器打开无 console 错误
7. 简短汇报：路径 + 内容 + 验证状态 + 下一步

变体默认至少 3 个：保守 / 强契合 / 发散（不是换色糊弄）。
用 action=workflow|variants|verify|anti_slop|full 获取对应完整章节。"""


async def run(args: dict, ctx) -> CapabilityResult:
    action = str(args.get("action") or "overview").strip().lower()
    brief = str(args.get("brief") or "").strip()
    body = read_skill_body(_DIR)

    if action == "overview":
        out = _OVERVIEW
        if brief:
            out += f"\n\n【当前 brief】{brief}"
        return CapabilityResult(ok=True, output=out)

    slices = {
        "workflow": (
            r"^## Workflow",
            r"^## Artifact Format",
        ),
        "variants": (
            r"^## Variation Rules",
            r"^## Tweakable Designs",
        ),
        "verify": (
            r"^## Verification",
            r"^## Final Response Format",
        ),
        "anti_slop": (
            r"^## Anti-Slop Rules",
            r"^## Typography",
        ),
    }

    if action in slices:
        start, end = slices[action]
        chunk = slice_between(body, start, end)
        if not chunk:
            return CapabilityResult(ok=False, error=f"未找到章节 action={action}")
        header = f"【claude_design · {action}】"
        if brief:
            header += f"\n【brief】{brief}\n"
        return CapabilityResult(ok=True, output=cap(f"{header}\n\n{chunk}"))

    if action == "full":
        header = "【claude_design · 完整规范】\n"
        if brief:
            header += f"【brief】{brief}\n\n"
        return CapabilityResult(ok=True, output=cap(header + body))

    return CapabilityResult(
        ok=False,
        error=f"未知 action={action}，可用: overview, workflow, variants, verify, anti_slop, full",
    )
