"""公众号排版回归 —— Markdown 转内联样式 HTML,不残留 markdown 符号。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.wechat import md_to_wechat_html


def test_basic_elements_become_inline_html():
    md = (
        "# 大标题\n\n"
        "## 小节\n\n"
        "Body text一段,含 **重点** 和 `代码`。\n\n"
        "> 这是一句引用\n\n"
        "- 列表项一\n- 列表项二\n\n"
        "---\n"
    )
    html = md_to_wechat_html(md, title="文章标题")
    # 关键元素都带内联 style
    assert "style=" in html
    assert "<h1" in html and "<h2" in html
    assert "<strong" in html and "<code" in html
    assert "<blockquote" in html and "<ul" in html and "<hr" in html
    # 不应残留 markdown 原始符号(标题井号 / 列表破折号开头 / 引用尖括号)
    assert "# 大标题" not in html
    assert "\n- 列表项" not in html
    assert "> 这是一句引用" not in html


def test_escapes_html_in_content():
    html = md_to_wechat_html("Body text带 <script>alert(1)</script> 标签")
    assert "<script>alert" not in html      # 已转义
    assert "&lt;script&gt;" in html


def test_image_placeholder_when_no_url():
    html = md_to_wechat_html("![封面图]()")
    assert "配图位" in html
