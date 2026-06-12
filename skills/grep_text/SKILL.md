---
name: grep_text
description: 在目录中跨文件搜索字符串或正则,返回文件、行号与匹配内容
trigger: 搜索 查找 grep 哪里用了 出现在 包含
risk: READ
---

# grep_text

在一个目录下逐文件搜索内容(对应命令行的 grep/ripgrep)。用来回答"这个词/函数/配置
在哪些文件第几行出现过"。自动跳过 `.venv`/`.git`/`__pycache__`/`logs` 等噪声目录。

输入参数:
- `query`(string):要搜索的字符串或正则。
- `path`(string,可选):搜索目录,默认当前目录。
- `regex`(boolean,可选):query 是否按正则解释,默认 false(按字面)。
- `ext`(string,可选):只搜某扩展名,如 `.py`。
- `max_results`(integer,可选):最多返回匹配行数,默认 50。
