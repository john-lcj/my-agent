---
name: pptx_writer
description: 依据大纲一键生成PPT演示文稿,每页含标题与若干要点条目
trigger: ppt pptx 幻灯片 演示 deck slides 汇报
risk: WRITE
---

# pptx_writer

把大纲写成 `.pptx` 演示文稿。大纲格式:以 `# 标题` 开一页(标题页/章节),
其下的 `- 要点` 行作为该页的要点条目。

输入参数:
- `path`(string,必填):输出 .pptx 路径。
- `outline`(string,必填):大纲文本(`# 页标题` + `- 要点`)。
- `title`(string,可选):封面主标题。

输出:生成的文件路径与页数。
