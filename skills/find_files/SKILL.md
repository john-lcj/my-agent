---
name: find_files
description: 按文件名通配符在指定目录下递归查找文件,自动跳过噪声目录
trigger: 找文件 哪个文件 find 列出 所有 .py 文件
risk: READ
---

# find_files

在一个目录下递归查找文件名匹配通配符的文件(对应 glob)。用来回答"项目里有哪些
`*.yaml`""那个 `index.*` 在哪"。自动跳过 `.venv`/`.git`/`__pycache__` 等噪声目录。

输入参数:
- `pattern`(string):文件名通配,如 `*.py`、`*.md`、`index.*`。
- `path`(string,可选):起始目录,默认当前目录。
- `max_results`(integer,可选):最多返回数,默认 100。
