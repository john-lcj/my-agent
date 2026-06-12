---
name: text_diff
description: 对比两段文本,输出统一 diff、相似度与新增/删除行数
trigger: 对比 差异 diff 比较 改动
risk: READ
---

# text_diff

逐行对比两段文本,给出相似度百分比、新增/删除了多少行,以及标准的统一 diff
(`+` 新增、`-` 删除)。适合看两个版本的改动。

输入参数:
- `a`(string):原文本。
- `b`(string):新文本。
