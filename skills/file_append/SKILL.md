---
name: file_append
description: 向文件末尾追加内容(文件不存在则创建),不覆盖原内容
trigger: 追加 append 续写 加到末尾 记一笔
risk: WRITE
---

# file_append

往文件末尾追加文本,而不是覆盖整文件(对应 shell 的 `>>`)。适合往日志/清单/笔记里
不断累加。文件不存在会自动创建。

输入参数:
- `path`(string):文件路径。
- `content`(string):要追加的文本。
- `newline`(boolean,可选):追加前是否先补一个换行,默认 true。
