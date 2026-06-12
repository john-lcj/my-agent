---
name: personal_search
description: 在主人的个人笔记与文档的索引中做语义检索,返回片段与来源
trigger: 我笔记 我的笔记 我之前写过 我的文档 我记过 笔记里
risk: READ
---

# personal_search

当主人问"我笔记里写过什么""我之前怎么想的""帮我找找我的文档"这类问题时使用。

前提:已配置 `AGENT_PERSONAL_DIRS` 并完成索引(服务启动后由定时任务「个人数据索引」
自动维护,也可在 Web 定时任务页手动运行一次)。

输入参数:
- `query`(string):要检索的内容描述。
- `k`(int,可选):返回片段数,默认 5。

输出:每条命中片段附 `[file:路径#块号]` 来源标记,可继续用 fs.read 读原文。
