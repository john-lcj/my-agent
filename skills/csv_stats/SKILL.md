---
name: csv_stats
description: 读取表格文件或文本,给出行列概览、每列类型与缺失值的统计
trigger: csv 表格 数据 统计 分析 列
risk: READ
---

# csv_stats

当用户想快速了解一个 CSV 数据的概况时使用:有多少行多少列、每列是数值还是文本、
数值列的最小/最大/均值/中位数、各列缺失了多少。

输入参数(`path` 与 `csv_text` 二选一):
- `path`(string):CSV 文件路径。
- `csv_text`(string):直接传入的 CSV 文本。
- `delimiter`(string,可选):分隔符,默认 `,`。
