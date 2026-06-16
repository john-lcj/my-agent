---
name: pdf_extract
description: 提取PDF文档的文本内容,可按指定页码范围读取并摘录正文
trigger: pdf 文档 提取 读取 解析 论文 合同
risk: READ
---

# pdf_extract

从 PDF 文件中提取纯文本,供阅读、摘录、分析。可选页码范围(如只看前几页)。

输入参数:
- `path`(string,必填):PDF 文件路径。
- `pages`(string,可选):页码范围,如 `1-5` 或 `3`;留空读全部。
- `max_chars`(number,可选):最多返回字符数,默认 8000,防止超长。

输出:提取到的文本(含页数信息);失败时给出原因。
