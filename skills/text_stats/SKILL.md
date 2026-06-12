---
name: text_stats
description: 统计一段文本的字符数、词数、行数。
trigger: 统计 文本 字数 行数
risk: READ
---

# text_stats

当用户想知道一段文本有多少字符/词/行时使用本 skill。

输入参数:
- `text`(string):要统计的文本。

这是一个示例 skill,演示插件系统:把目录丢进 skills/ 即可被自动发现并加载,
无需改动主循环或治理层。
