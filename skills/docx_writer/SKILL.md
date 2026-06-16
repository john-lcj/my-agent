---
name: docx_writer
description: 把文本或Markdown生成Word文档,含标题段落表格
trigger: word docx 文档 报告 公文 letter 信函
risk: WRITE
---

# docx_writer

把 Markdown/纯文本写成 `.docx` Word 文档。识别 `#`/`##`/`###` 标题、普通段落、
以及 `|` 分隔的表格行,生成带层级标题与表格的可打开 Word 文件。

输入参数:
- `path`(string,必填):输出 .docx 路径(如 `logs/reports/x.docx`)。
- `markdown`(string,必填):正文(Markdown 或纯文本)。
- `title`(string,可选):文档大标题。

输出:生成的文件路径与段落/表格数量。
