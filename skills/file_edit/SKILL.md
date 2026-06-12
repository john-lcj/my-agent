---
name: file_edit
description: 在指定文件中精确查找并替换文本,原地编辑带唯一性校验保护
trigger: 修改 编辑 替换 改文件 改一行 把..改成
risk: WRITE
---

# file_edit

对已有文件做"查找 → 替换",而不是整文件覆盖。默认要求待替换文本在文件中**唯一**
(避免改错地方);需要全部替换时传 `replace_all=true`。

输入参数:
- `path`(string):文件路径。
- `old`(string):要替换掉的原文本(默认需唯一,否则报错提示扩大上下文)。
- `new`(string):替换成的新文本。
- `replace_all`(boolean,可选):替换全部匹配,默认 false。
