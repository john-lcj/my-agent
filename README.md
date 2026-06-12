# my-agent

一个有"分寸感"的 agent 平台骨架。

设计哲学一句话:**循环很笨,治理很严,观测很全,放手很安心。**
对过程激进(读/想/试全自主),对决策保守(删/改/花钱/不可逆才回来问。

## 当前状态

- ✅ **单 agent 闭环**:感知 → 规划 → 治理 → 行动 → 反思(mock 与真实 DeepSeek 均验证)。
- ✅ **系统提示词**(分寸原则 + 动态能力清单);**严格工具配对协议**(多步链路稳定)。
- ✅ **治理**:声明式策略、硬/软边界、可解释裁决(`GOVERNANCE_DECISION`)、本会话授权放手。
- ✅ **可回滚**:写/删前自动快照;CLI `/rollback` 与 Web `/rollback` / WS 回滚。
- ✅ **记忆**:工作记忆摘要 + **混合长期记忆**(SQLite 关键词 + 向量语义,RAG);定时记忆清理任务。
- ✅ **Web 聊天界面**:FastAPI + WebSocket + **真 token 流式** + 确认卡片 + 治理事件展示 + 服务端 provider 配置。
- ✅ **skill 插件系统**:目录化自动发现 + 懒加载 + READ skill 按任务自动路由预取(`skills/router.py`);
  内置 `text_stats` / `readability_score` / `keyword_extract` / `notify_dispatch` / `personal_search` 及指导型 `claude_design` / `design_taste_frontend`。
- ✅ **多 agent(模式 A+)**:Captain 先自治(默认 `AGENT_CAPTAIN_MAX_STEPS=8` 步),解决不了**自动升级专家**(AutoDispatcher 选人 + 移交尝试摘要);`/专家名` 可显式直达;圆桌/Hierarchical/辩论编排保留。
- ✅ **专家收编(5 人,权限差异化)**:code(代码+shell)/ data_analyst(数据+shell,产物 `logs/reports/`)/ web(网页+联网)/ ops_notify(唯一真实推送)/ adler_counselor(纯对话+记忆);权限写在 `governance/policy.yaml` 白名单(roles=专家名,**默认拒绝**),不靠 prompt。
- ✅ **偏好自动沉淀**:会话结束后自动抽取耐用偏好写入长期记忆,下次开场注入(persona 管恒定人格,偏好记忆管动态认知);`GET/DELETE /api/memory/preferences` 可查看/删除。
- ✅ **每日简报**:启动时幂等注册 daily 定时任务(默认 08:00 → QQ,`AGENT_BRIEFING_*` 配置),agent 汇总待办/要点/建议后主动推送。
- ✅ **个人数据接入(只读)**:`AGENT_PERSONAL_DIRS` 目录增量索引进向量记忆(每天 03:30 自动,Web 任务页可手动跑);`personal_search` skill 语义检索,"我笔记里"等说法自动路由。
- ✅ **真实任务评测**:`python -m eval.run_real` 用真模型跑 `eval/personal/tasks.yaml`(10 个预置任务,LLM 评委打分),报告落 `logs/eval_reports/` 并与上次对比。
- ✅ **GUI 控制**:macOS 截图/点击/键入(需辅助功能权限,默认 ASK)。
- ✅ **外部渠道**:邮件 / 企业微信 / QQ / **Slack / Telegram** webhook;与 Web 一样走 **Coordinator** 派活。
- ✅ **程序记忆**:结构化 KV(`program.remember` / `program.recall` / `program.list`)。
- ✅ **联网搜索**:`web.search` + `web.fetch`(默认 DuckDuckGo;可选 Tavily / Brave / Serper)。
- ✅ **Context 门面**:`ConversationLog` + `SessionAttachment` 拆分(对外仍用 `Context`)。
- ✅ **多模型**:Claude / OpenAI / DeepSeek / **Ollama(本地)** + Router;`AGENT_EMBED_PROVIDER` 配置向量嵌入。
- ✅ **辩论编排**:正反方交替 + 主持人总结(WebSocket `debate_start`)。
- ✅ **分级治理**:conservative / balanced / aggressive 档位(Web 设置可写 runtime)。
- ✅ **资源互斥锁**:写同一文件的并行任务自动串行化,占用超时按失败返回(防互相覆盖)。
- ✅ **回归测试**:`python -m tests.harness`(49 项)或 `pytest -q tests/test_regression.py`;真模型质量评测见 `eval/run_real.py`。

## 快速开始

配置一次后,终端任意目录输入:

```bash
my agent        # 启动 Web → http://127.0.0.1:8000
my agent cli    # 终端对话
my agent stop   # 停止 Web 服务
```

(命令已写入 `~/.zshrc`;新开终端或执行 `source ~/.zshrc` 后生效。)

```bash
# 零依赖直接跑(用 MockLLM)
python main.py

# 跑回归测试(确定性,无需 key)
python -m tests.harness
pytest -q tests/test_regression.py

# 启动 Web 聊天界面,浏览器打开 http://127.0.0.1:8000
pip install -r requirements.txt
uvicorn server.app:app --port 8000
```

试试这些输入:

```
读 README.md
写 logs/hi.txt :: 你好世界
跑 echo hello
/rollback
```

写文件/跑命令/GUI 会触发**确认**(软边界);`rm -rf`、写 `.env` 之类会被**直接拒绝**(硬边界)。

用真实模型:

```bash
cp .env.example .env      # 填入 key,设 AGENT_PROVIDER=deepseek/openai/claude
pip install -r requirements.txt
python main.py
```

环境变量补充:

| 变量 | 说明 |
|------|------|
| `AGENT_PROVIDER` | mock / deepseek / openai / claude / router |
| `AGENT_EMBED_PROVIDER` | mock(默认) / openai — 向量记忆嵌入 |
| `AGENT_MAX_COST_USD` | 单次会话金额上限 |
| `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | 本地 Ollama 模型与 API 地址 |
| `AGENT_GOVERNANCE_MODE` | conservative / balanced / aggressive |
| `AGENT_CAPTAIN_MAX_STEPS` | 模式 A+:Captain 自治步数上限,用尽后升级专家(默认 8) |
| `AGENT_PREF_MINING` | 偏好自动沉淀开关(默认 on;mock 模型自动关) |
| `AGENT_PERSONAL_DIRS` | 个人数据目录(只读索引,冒号分隔) |
| `AGENT_BRIEFING_AT` / `AGENT_BRIEFING_CHANNEL` / `AGENT_BRIEFING_TO` | 每日简报时间/渠道/投递目标 |
| `TAVILY_API_KEY` / `SERPER_API_KEY` / `BRAVE_SEARCH_API_KEY` | 可选,提升搜索质量 |

## 架构(六层 + 脊椎)

```
channels/        外部接口(cli / web / 邮件 / 微信 / QQ)
core/loop.py     编排器:只依赖接口的主循环(agent 心脏)
core/bootstrap.py + coordinator_stack.py  统一装配
core/bus.py      事件总线:平台脊椎
governance/      ★ 治理层:统一收口审查(分寸感所在)
capabilities/    统一能力层:工具/GUI/skill/委托
memory/          working + hybrid(SQLite+Vector) 长期记忆
observability/   trace + rollback
agents/          Coordinator / 圆桌 / roster 专家
server/          FastAPI + events 协议 + 治理统计 API
```

## 核心设计决策

- **统一能力管线**:调工具、跑 skill、控 GUI、委托子 agent 都收敛成 `CapabilityCall`,
  治理层只有一个收口要审查 —— 加再多能力,安全模型也不分裂。
- **安全由代码保证,不靠 prompt**:硬边界写在 `governance/`,模型无法绕过。
- **治理三参数签名** `review(call, actor, ctx)`:从第一天为多 agent/多用户的按主体鉴权预留。
- **事件总线从第一天就立**:单向通知走总线,双向确认走回调;`server/events.to_wire` 为前后端契约。
- **模型面向接口**:换厂商/本地只改 `llm/factory.py` 与组合根 profile。

## 路线图(后续)

- 辩论模式 Web UI 入口(当前可用 WS:`debate_start`)
- Slack/Telegram 群组策略、程序记忆治理细规则
