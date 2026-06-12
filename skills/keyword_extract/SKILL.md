---
name: keyword_extract
description: 从文本中按词频提取最高频的若干个关键词,并过滤常见停用词
trigger: 关键词 标签 词频 提取
risk: READ
---

# keyword_extract

用于营销卖点提炼、调研报告标签、SEO 方向参考。

输入参数:
- `text`(string, 必填): 源文本
- `top_n`(integer, 可选): 返回条数，默认 10
