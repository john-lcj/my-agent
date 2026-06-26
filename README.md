# my-agent

一个有"分寸感"的 AI Agent 平台 —— 从零搭建，跑在 DeepSeek 上。

设计哲学一句话：**循环很笨，治理很严，观测很全，放手很安心。**
对过程激进（读/想/试全自主），对决策保守（删/改/花钱/不可逆才回来问）。

> ⚠️ **定位**：本项目面向**个人 / 可信网络环境**，默认绑定 `127.0.0.1`。它会在宿主机上
> 执行 shell、读写文件——治理层提供"分寸"约束，但不是沙箱。**未经额外加固（`/ws` 鉴权、
> shell 沙箱化、多用户隔离），请勿对公网开放或作为多用户在线服务。** 详见 [SECURITY.md](SECURITY.md)。

## 60 秒快速开始

**方式一 · 本机（有 Python）**

```bash
make setup     # 创建 .venv 并装好依赖（首次）
make web       # 启动网页 → http://127.0.0.1:8000
make cli       # 或：终端对话（MockLLM 零配置即可跑）
```

**方式二 · Docker（零环境依赖）**

```bash
echo "AGENT_API_TOKEN=$(openssl rand -hex 16)" >> .env   # 容器访问需令牌
make docker-up                                            # = docker compose up -d --build
# 打开 http://127.0.0.1:8000 → 设置 →「访问令牌」填入上面的 token 即可使用
```

> 没有 `make`？对应命令见下文与 `Makefile`。要用真实模型，在 `.env` 配 `DEEPSEEK_API_KEY`
> 等并参考[质量评测](#质量评测用真实模型跑)一节。

## 当前状态（~29,000 行，75 个 commit）

- ✅ **单 agent 闭环**：感知 → 规划 → 治理 → 行动 → 反思（Mock 与 DeepSeek 均验证）。
- ✅ **Cowork 模式**：Captain 先自治（默认 8 步），用尽自动升级专家，走 map-reduce DAG 编排。
- ✅ **动态子代理**：researcher / executor 按权限档差异化（code / data_analyst / web / ops_notify / adler_counselor），权限写在 `governance/policy.yaml` 白名单，不靠 prompt。
- ✅ **Graph 编排**：依赖感知 DAG 规划 + 并发执行闸 + 重试退避；绑 `AGENT_MAX_PARALLEL`，DeepSeek 实测串行最稳。
- ✅ **Projects / Artifacts / 上传**：项目维度的文件产物管理，前端借鉴 Claude 设计。
- ✅ **治理**：声明式策略、硬/软边界（BLOCK / ASK）、可解释裁决、三级档位（conservative / balanced / aggressive）、RBAC 白名单。
- ✅ **可回滚**：写/删前自动快照；CLI `/rollback` + Web `/rollback` / WS 回滚。
- ✅ **记忆系统**：工作记忆摘要 + 混合长期记忆（SQLite 关键词 + 向量语义 RAG）+ 经验自动沉淀 + 偏好自动挖掘 + 伙伴记忆（会话结束自动沉淀，下次开场注入"上次到哪了"）。
- ✅ **Web 聊天界面**：FastAPI + WebSocket + 真 token 流式 + 确认卡片 + 治理事件展示 + Cowork 工作台（进度 + 产物一览）。
- ✅ **Skill 插件系统**：28 个内置 skill（docx/pptx/xlsx/pdf/http/git/calendar/邮件/通知/搜索/写作/设计等），目录化自动发现 + 懒加载 + 按任务自动路由。
- ✅ **MCP 连接器**：接入外部 MCP server 工具（文件系统/Git/数据库/Notion…），和内置工具一样过治理。
- ✅ **多模型**：DeepSeek / OpenAI / Claude / Ollama（本地）+ Router + Fallback 降级；权限档分模型（executor 强模型 / researcher 快模型）。
- ✅ **GUI 控制**：macOS 截图/点击/键入（需辅助功能权限，默认 ASK）。
- ✅ **外部渠道**：邮件（IMAP 轮询 + SMTP 发信 + 白名单）+ Web 界面。
- ✅ **每日简报**：启动时幂等注册定时任务，agent 汇总待办/要点/建议后邮件推送。
- ✅ **个人数据接入**：`AGENT_PERSONAL_DIRS` 目录增量索引进向量记忆，`personal_search` 语义检索。
- ✅ **联网搜索**：`web.search` + `web.fetch`（默认 DuckDuckGo；可选 Tavily / Brave / Serper / Exa）。
- ✅ **上下文门面**：`ConversationLog` + `SessionAttachment` 拆分 + 抗抖动/防 thrash/抗谄媚机制。
- ✅ **可观测**：全链路 trace + 审计日志 + 事务回滚 + Egress 审查 + 资源互斥锁。
- ✅ **质量评测**：55 个回归测试 + 40 例真实模型评测（LLM 评委打分，报告对比）。
- ✅ **一键安装**：`uvx` / `pipx` / `pip install -e` 三种方式；macOS LaunchAgent / Windows 计划任务开机自启。
- ✅ **安全硬化**：工作区文件范围限制 + 防注入外发白名单 + `/ws` 鉴权 + shell 沙箱钩子 + 前端 token。

## 快速开始

配置一次后，终端任意目录输入：

```bash
myagent          # 启动 Web → http://127.0.0.1:8000
myagent cli      # 终端对话
myagent stop     # 停止 Web 服务
```

（命令已写入 `~/.zshrc`；新开终端或执行 `source ~/.zshrc` 后生效。）

```bash
# 零依赖直接跑（用 MockLLM）
python main.py

# 跑回归测试（确定性，无需 key）
pytest -q tests/

# 启动 Web 聊天界面，浏览器打开 http://127.0.0.1:8000
pip install -r requirements.txt
uvicorn server.app:app --port 8000
```

## 安装与分享（开源分发）

项目已打包，可作为命令行工具安装，装好后在终端任意位置直接敲 `myagent`。

```bash
# 方式一：零安装运行（uv，推荐别人快速试）
uvx --from "git+https://github.com/john-lcj/my-agent" myagent          # 终端对话
uvx --from "git+https://github.com/john-lcj/my-agent[web]" myagent-web   # Web 界面

# 方式二：用 pipx 常驻安装
pipx install "git+https://github.com/john-lcj/my-agent"
pipx install "git+https://github.com/john-lcj/my-agent[all]"   # 含真实模型/Web/记忆/渠道全部依赖
myagent          # 终端对话（MockLLM 零依赖即可跑）
myagent-web      # 启动 Web → http://127.0.0.1:8000

# 方式三：克隆后可编辑安装（开发推荐，相对路径最稳）
git clone https://github.com/john-lcj/my-agent && cd my-agent
pip install -e ".[all]"
myagent
```

依赖按需取用：基座零依赖（MockLLM）；`[llm]` 真实模型、`[web]` Web 服务、
`[memory]` 向量记忆、`[channels]` 外部渠道、`[cli]` 斜杠补全、`[mcp]` MCP 连接器、
`[office]` Office 文档生成/解析、`[all]` 全部。

> 安全：`myagent-web` 默认绑 `127.0.0.1`。若改用 `AGENT_WEB_HOST=0.0.0.0` 对外暴露，
> 务必先设 `AGENT_API_TOKEN`，否则 `/api/*` 控制面将无认证（见鉴权中间件）。

## 质量评测（用真实模型跑）

回归测试（MockLLM）保证"水管不漏"；真实模型评测回答"答案好不好"。在你本机（已配
`DEEPSEEK_API_KEY`）运行——用项目自带的 `.venv`，从本地目录安装：

```bash
cd "~/Desktop/Projects/my agent"                                  # 进项目目录
.venv/bin/python -m pip install -e ".[llm]"                       # 装 openai SDK（DeepSeek 走兼容协议）
.venv/bin/python -m eval.run_real --model deepseek-v4-flash        # 全量 40 个任务，LLM 评委打分
.venv/bin/python -m eval.run_real --only code-explain              # 只跑某个任务
```

> macOS 上 `python`/`pip` 常不在 PATH（系统是 `python3`/`pip3`）。直接用 `.venv/bin/python`
> 最省事：不用激活、不依赖 PATH。

报告落在 `logs/eval_reports/YYYY-MM-DD.md`，并自动与上一份对比。把报告贴回来即可据此
迭代 system prompt / 编排策略。

## 连接外部工具（MCP 连接器）

通过 MCP（Model Context Protocol）接入任意外部 server 的工具（文件系统、Git、
数据库、Notion…）。它们会被包成 `mcp.<server>.<tool>` 能力，**和内置工具一样过治理**
（硬/软边界、按角色白名单、确认、计费）。

```bash
pip install "my-agent[mcp]"          # 安装 MCP SDK
cp mcp_servers.json.example mcp_servers.json   # 按需改成你的 server
myagent-web                          # 启动时自动连接并注册工具（日志打印 [mcp] ...）
```

风险默认 fail-safe：工具声明 `readOnlyHint` 才算只读放行，未声明一律按高危需确认。
连接失败/未装 SDK 时自动跳过，不影响其余功能。

试试这些输入：

```
读 README.md
写 logs/hi.txt :: 你好世界
跑 echo hello
/rollback
```

写文件/跑命令/GUI 会触发**确认**（软边界）；`rm -rf`、写 `.env` 之类会被**直接拒绝**（硬边界）。

用真实模型：

```bash
cp .env.example .env      # 填入 key，设 AGENT_PROVIDER=deepseek/openai/claude
pip install -r requirements.txt
python main.py
```

环境变量补充：

| 变量 | 说明 |
|------|------|
| `AGENT_PROVIDER` | mock / deepseek / openai / claude / router |
| `AGENT_EMBED_PROVIDER` | mock（默认）/ openai — 向量记忆嵌入 |
| `AGENT_MAX_COST_USD` | 单次会话金额上限 |
| `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | 本地 Ollama 模型与 API 地址 |
| `AGENT_GOVERNANCE_MODE` | conservative / balanced / aggressive |
| `AGENT_CAPTAIN_MAX_STEPS` | Captain 自治步数上限，用尽后升级专家（默认 8） |
| `AGENT_MAX_PARALLEL` | Cowork DAG 并发上限（默认 1，DeepSeek 实测串行最稳） |
| `AGENT_PREF_MINING` | 偏好自动沉淀开关（默认 on；mock 模型自动关） |
| `AGENT_PERSONAL_DIRS` | 个人数据目录（只读索引，冒号分隔） |
| `AGENT_BRIEFING_AT` / `AGENT_BRIEFING_CHANNEL` / `AGENT_BRIEFING_TO` | 每日简报时间/渠道/投递目标 |
| `AGENT_EXECUTOR_MODEL` / `AGENT_RESEARCHER_MODEL` | 按权限档分模型 |
| `TAVILY_API_KEY` / `SERPER_API_KEY` / `BRAVE_SEARCH_API_KEY` / `EXA_SEARCH_API_KEY` | 可选，提升搜索质量 |

## 架构（六层 + 脊椎）

```
channels/           外部接口（cli / web / 邮件）
core/loop.py        编排器：只依赖接口的主循环（agent 心脏）
core/bootstrap.py + coordinator_stack.py  统一装配
core/bus.py         事件总线：平台脊椎
governance/         ★ 治理层：统一收口审查 + 预算 + Egress 审查 + 资源锁
capabilities/       统一能力层：22 个工具（fs/shell/web/browser/git/calendar/plan/schedule…）+ GUI + MCP + skill 委托
memory/             混合长期记忆（SQLite + Vector）+ 经验/偏好/目标/检查点/反馈/项目/模板/秘密保险箱
observability/      trace + rollback + audit + transcript
agents/             Coordinator + GraphDispatcher + GraphOrchestrator + 子代理 + 圆桌
server/             FastAPI + events 协议 + WebSocket 流式 + 治理统计 + 用量统计
llm/                DeepSeek / OpenAI / Claude / Ollama / Mock + Router + Fallback 降级
scheduler/          定时任务调度（简报/索引/清理）
skills/             28 个内置 skill 插件（docx/pptx/xlsx/pdf/http/git/calendar/邮件/通知/搜索/写作/设计…）
evals/              40 例真实任务评测 + judge + scoring
```

## 核心设计决策

- **统一能力管线**：调工具、跑 skill、控 GUI、委托子 agent 都收敛成 `CapabilityCall`，
  治理层只有一个收口要审查 —— 加再多能力，安全模型也不分裂。
- **安全由代码保证，不靠 prompt**：硬边界写在 `governance/`，模型无法绕过。
- **治理三参数签名** `review(call, actor, ctx)`：从第一天为多 agent/多用户的按主体鉴权预留。
- **事件总线从第一天就立**：单向通知走总线，双向确认走回调；`server/events.to_wire` 为前后端契约。
- **模型面向接口**：换厂商/本地只改 `llm/factory.py` 与组合根 profile。
- **Cowork 模式强制 DAG**：复杂任务走 map-reduce，研究多对象时每个对象并行 researcher → 串行归约落盘。

## 路线图（后续）

- 辩论模式 Web UI 入口（当前可用 WS：`debate_start`）
- 手机经 Tailscale 直连 Web UI 的完整文档
- Obsidian 笔记集成
