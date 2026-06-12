---
name: table_format
description: 把 CSV/TSV 文本转成 Markdown 表格(自动识别分隔符)
trigger: 表格 markdown csv tsv 转表
risk: READ
---

# table_format

把粘来的 CSV / TSV / 制表符分隔的数据,转成可直接贴进文档的 Markdown 表格。

输入参数:
- `data`(string):带表头的 CSV/TSV 文本(首行为表头)。
- `delimiter`(string,可选):分隔符;留空自动识别(优先制表符,否则逗号)。
