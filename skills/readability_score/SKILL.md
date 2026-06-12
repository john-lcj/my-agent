---
name: readability_score
description: 评估文本可读性：句长、过长句占比、简易可读分。
trigger: 可读性 句长 润色 评分
risk: READ
---

# readability_score

对一段中文/英文混合文案做可读性分析，辅助文案润色与平台适配。

输入参数:
- `text`(string, 必填): 待分析文本
- `lang`(string, 可选): `zh` 或 `auto`，默认 `auto`
