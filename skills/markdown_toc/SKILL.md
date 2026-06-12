---
name: markdown_toc
description: 扫描各级标题生成带锚点链接的目录,可设层级跳过代码块内容
trigger: 目录 toc markdown 大纲 标题
risk: READ
---

# markdown_toc

扫描一段 Markdown 的各级标题,生成带锚点链接的目录,贴回文档顶部即可。
会跳过代码块里的 `#`,不会误当标题。

输入参数:
- `markdown`(string):Markdown 文本。
- `max_level`(integer,可选):纳入目录的最大标题层级,默认 3。
