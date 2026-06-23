"""公众号排版能力 —— 把正文转成可直接粘进公众号编辑器的内联样式 HTML。

为什么需要:公众号编辑器**不认 Markdown**,贴进 # / - / ** 只会原样显示。
本能力把 Markdown/纯文本转成**带内联 style 的 HTML**(微信会保留内联样式),
覆盖:一/二级标题、正文段、无序/有序列表、引用卡片、重点色块、分割线、
加粗、行内代码、配图位占位。产出可直接全选复制到公众号后台。
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

# —— 一套克制、移动端可读的公众号视觉(深灰正文 + 主题色点缀)——
ACCENT = "#07689f"        # 主题色(标题色条 / 链接 / 重点)
_BODY = ("font-size:16px;line-height:1.75;color:#333;"
         "letter-spacing:.3px;word-break:break-word;margin:18px 0;")


def _inline(text: str) -> str:
    """行内:**加粗**、`代码`、[文字](链接) → 内联样式 HTML(先转义)。"""
    t = _html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#222;font-weight:600">\1</strong>', t)
    t = re.sub(r"`([^`]+?)`",
               r'<code style="background:#f2f4f6;color:#c7254e;padding:1px 5px;'
               r'border-radius:3px;font-size:14px">\1</code>', t)
    t = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)",
               rf'<a href="\2" style="color:{ACCENT};text-decoration:none">\1</a>', t)
    return t


def md_to_wechat_html(md: str, title: str = "") -> str:
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    if title:
        out.append(
            f'<h1 style="font-size:22px;font-weight:700;color:#222;'
            f'text-align:center;margin:8px 0 22px;line-height:1.4">{_html.escape(title)}</h1>'
        )
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()
        if not s:
            i += 1
            continue
        # 分割线
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            out.append('<hr style="border:none;border-top:1px solid #e6e6e6;margin:26px 0"/>')
            i += 1
            continue
        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            txt = _inline(m.group(2))
            if level == 1:
                out.append(f'<h1 style="font-size:21px;font-weight:700;color:#222;'
                           f'margin:28px 0 16px;line-height:1.4">{txt}</h1>')
            elif level == 2:
                out.append(
                    f'<h2 style="font-size:18px;font-weight:700;color:#222;'
                    f'margin:26px 0 14px;padding-left:10px;line-height:1.5;'
                    f'border-left:4px solid {ACCENT}">{txt}</h2>')
            else:
                out.append(f'<h3 style="font-size:16px;font-weight:600;color:{ACCENT};'
                           f'margin:22px 0 10px">{txt}</h3>')
            i += 1
            continue
        # 引用卡片(连续 > 合并)
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(_inline(re.sub(r"^\s*>\s?", "", lines[i])))
                i += 1
            inner = "<br/>".join(buf)
            out.append(
                f'<blockquote style="margin:18px 0;padding:14px 16px;background:#f6f9fb;'
                f'border-left:4px solid {ACCENT};border-radius:4px;color:#555;'
                f'font-size:15px;line-height:1.7">{inner}</blockquote>')
            continue
        # 配图位:![alt](url) 或 [图:xxx]
        mi = re.match(r"^!\[(.*?)\]\((.*?)\)$", s)
        if mi:
            alt = _html.escape(mi.group(1)); url = mi.group(2).strip()
            if url:
                out.append(f'<p style="text-align:center;margin:18px 0">'
                           f'<img src="{url}" alt="{alt}" style="max-width:100%;border-radius:6px"/></p>')
            else:
                out.append(f'<p style="text-align:center;color:#aaa;font-size:14px;'
                           f'border:1px dashed #ccc;padding:24px;border-radius:6px;margin:18px 0">'
                           f'【配图位{("·" + alt) if alt else ""}】</p>')
            i += 1
            continue
        # 无序列表
        if re.match(r"^[-*+]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(_inline(re.sub(r"^\s*[-*+]\s+", "", lines[i])))
                i += 1
            lis = "".join(
                f'<li style="margin:6px 0;padding-left:4px">{it}</li>' for it in items)
            out.append(f'<ul style="{_BODY}padding-left:22px">{lis}</ul>')
            continue
        # 有序列表
        if re.match(r"^\d+[.、)]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.、)]\s+", lines[i]):
                items.append(_inline(re.sub(r"^\s*\d+[.、)]\s+", "", lines[i])))
                i += 1
            lis = "".join(
                f'<li style="margin:6px 0;padding-left:4px">{it}</li>' for it in items)
            out.append(f'<ol style="{_BODY}padding-left:22px">{lis}</ol>')
            continue
        # 普通段落
        out.append(f'<p style="{_BODY}">{_inline(s)}</p>')
        i += 1

    inner = "\n".join(out)
    return (f'<section style="max-width:677px;margin:0 auto;padding:0 2px;'
            f'font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\',sans-serif">'
            f'\n{inner}\n</section>')


class WechatFormat(Tool):
    name = "wechat.format"
    risk = Risk.READ
    description = (
        "把文章正文(Markdown/纯文本)排成可直接粘进公众号编辑器的内联样式 HTML"
        "(标题层级、引用卡片、重点、分割线、配图位)。写公众号推文时务必用它产出最终稿。"
    )
    schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "文章正文(支持 Markdown 语法)"},
            "title": {"type": "string", "description": "文章标题(可选,会居中加粗置顶)"},
        },
        "required": ["content"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        content = str(args.get("content", "")).strip()
        if not content:
            return CapabilityResult(ok=False, error="缺少 content")
        html = md_to_wechat_html(content, str(args.get("title", "")).strip())
        return CapabilityResult(ok=True, output=html)
