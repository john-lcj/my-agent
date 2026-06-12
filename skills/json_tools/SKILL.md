---
name: json_tools
description: 校验 / 美化 / 压缩 JSON,或列出顶层键(报错会定位到行列)
trigger: json 格式化 校验 美化 压缩
risk: READ
---

# json_tools

处理一段 JSON 文本:检查是否合法、美化缩进、压缩成一行、或列出顶层键及其类型。
JSON 非法时会指出出错的行号与列号,便于定位。

输入参数:
- `json_text`(string):JSON 文本。
- `action`(string,可选):`validate` 校验 / `pretty` 美化(默认)/ `minify` 压缩 / `keys` 列顶层键。
