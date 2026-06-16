---
name: xlsx_writer
description: 把表格数据或CSV写成Excel文件,支持多列与表头生成
trigger: excel xlsx 表格 报表 spreadsheet 工作表
risk: WRITE
---

# xlsx_writer

把数据写成 `.xlsx` Excel 文件。数据来源二选一:`rows`(二维数组)或 `csv_text`
(CSV 文本)。首行作表头并加粗。

输入参数:
- `path`(string,必填):输出 .xlsx 路径。
- `rows`(array,可选):二维数组,每行一个数组。
- `csv_text`(string,可选):CSV 文本(与 rows 二选一)。
- `sheet`(string,可选):工作表名,默认 Sheet1。

输出:生成的文件路径与行列数。
