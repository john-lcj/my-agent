---
name: keyword_extract
description: 从文本提取 Top-N 关键词/短语（词频+停用词过滤）。
trigger: 关键词 标签 词频 提取
risk: READ
---

# keyword_extract

用于营销卖点提炼、调研报告标签、SEO 方向参考。

输入参数:
- `text`(string, 必填): 源文本
- `top_n`(integer, 可选): 返回条数，默认 10
