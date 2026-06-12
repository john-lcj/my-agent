"""design_taste_frontend: 反 AI 味前端规范（guidance skill）。"""
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
            "description": "overview | design_read | preflight | anti_tells | full",
            "default": "overview",
        },
        "brief": {"type": "string", "description": "设计 brief，design_read 时必填"},
    },
}

_DELIVERY_CONTRACT = """【交付契约 — 必须遵守,优先级高于一切设计发挥】
本 skill 的产出是「代码」,不是「设计说明」。无论做什么页面:
1. 必须产出一个**完整、可直接用浏览器打开的单文件 HTML**(CSS/JS 全部内联,不依赖外部文件)。
2. 必须用 fs.write 把该 HTML 写入一个具体文件(如工作目录下的 index.html),并在最终回复里
   给出**真实文件路径**与一句预览方式(如"用浏览器打开此文件")。
3. 严禁只输出设计描述/结构表格/拨盘说明而不写代码;严禁声称"已打开浏览器""页面已生成并打开"
   等你并未实际执行的动作——只陈述你真正做过的事。
完成标准 = 文件已写入 + 回复含真实路径。三者缺一即视为未完成。"""

_OVERVIEW = _DELIVERY_CONTRACT + """

【design_taste_frontend 摘要】
开始前先输出一行 Design Read:
「Reading this as: <page kind> for <audience>, with a <vibe> language, leaning toward <system/aesthetic>.」
然后**立即开始写完整 HTML 代码**(别停在描述阶段)。

三拨盘（默认 8/6/4，按 brief 调整）：
- DESIGN_VARIANCE — 布局对称 vs 不对称
- MOTION_INTENSITY — 静态 vs 电影感动效
- VISUAL_DENSITY — 画廊留白 vs 驾驶舱密度

交付前可跑 Pre-flight（action=preflight)自查。
禁止默认：AI 紫渐变、三 equal 卡片、Inter 默认、em-dash、假截图 div。

用 action=design_read|preflight|anti_tells|full 获取完整章节。"""


async def run(args: dict, ctx) -> CapabilityResult:
    action = str(args.get("action") or "overview").strip().lower()
    brief = str(args.get("brief") or "").strip()
    body = read_skill_body(_DIR)

    if action == "overview":
        out = _OVERVIEW
        if brief:
            out += f"\n\n【当前 brief】{brief}\n请先声明 Design Read，再写代码。"
        return CapabilityResult(ok=True, output=out)

    if action == "design_read":
        chunk = slice_between(
            body,
            r"^## 0\. BRIEF INFERENCE",
            r"^## 1\. THE THREE DIALS",
        )
        if not chunk:
            return CapabilityResult(ok=False, error="未找到 Design Read 章节")
        header = _DELIVERY_CONTRACT + "\n\n【design_taste_frontend · Design Read】\n"
        if brief:
            header += f"【brief】{brief}\n请先输出一行 Design Read，随后立即写完整 HTML 并 fs.write 落盘。\n\n"
        dials = slice_between(
            body,
            r"^## 1\. THE THREE DIALS",
            r"^## 2\. BRIEF",
        )
        return CapabilityResult(ok=True, output=cap(f"{header}{chunk}\n\n{dials}"))

    slices = {
        "preflight": (
            r"^## 14\. FINAL PRE-FLIGHT CHECK",
            r"^# APPENDICES",
        ),
        "anti_tells": (
            r"^## 9\. AI TELLS",
            r"^## 10\. REFERENCE VOCABULARY",
        ),
    }

    if action in slices:
        start, end = slices[action]
        chunk = slice_between(body, start, end)
        if not chunk:
            return CapabilityResult(ok=False, error=f"未找到章节 action={action}")
        header = f"【design_taste_frontend · {action}】\n"
        if brief:
            header += f"【brief】{brief}\n\n"
        return CapabilityResult(ok=True, output=cap(f"{header}{chunk}"))

    if action == "full":
        header = "【design_taste_frontend · 完整规范】\n"
        if brief:
            header += f"【brief】{brief}\n\n"
        return CapabilityResult(ok=True, output=cap(header + body))

    return CapabilityResult(
        ok=False,
        error=f"未知 action={action}，可用: overview, design_read, preflight, anti_tells, full",
    )
