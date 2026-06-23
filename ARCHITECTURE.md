# Captain · 架构总览

> 一个跑在 DeepSeek 上的多智能体平台:听懂目标 → 自己拆解执行 → 治理可审计。
> 后端纯 Python,前端单文件原生 HTML/JS。

## 技术栈

| 领域 | 选型 |
|---|---|
| 语言/运行时 | Python 3.10+ |
| Web 服务 | FastAPI + uvicorn + websockets（`/api/*` REST + `/ws` 实时流）|
| 前端 | **单文件原生 HTML/JS**（`frontend/index.html`，无框架，自管 i18n）|
| LLM | OpenAI SDK（DeepSeek 走 OpenAI 兼容协议）+ Anthropic SDK（Claude）；`tiktoken` 计 token |
| 存储/记忆 | SQLite（会话、定时任务）+ `sqlite-vec` + `numpy`（向量记忆）|
| 配置 | YAML（治理策略、专家 roster、persona）|
| 渠道 | `aiohttp`（web 搜索/抓取）、`aiosmtplib`/`aioimaplib`（邮件）|
| 测试 | pytest（30+ 文件）|
| 部署 | launchd 自启（mac）/ Docker；`scripts/launch.sh` 启动器 |

## 模块分布（后端约 1.3 万行 + 前端 6.7k）

| 模块 | 行数 | 职责 |
|---|---|---|
| **agents** | ~2850 | 多智能体编排核心：coordinator（Captain 先自治→升级专家）、graph_dispatcher（map-reduce 规划）、graph_orchestrator（DAG 执行 + 并发闸）、worker、roundtable、roster |
| **server** | ~2040 | FastAPI app + WebSocket + 所有 `/api` 端点、runtime 配置、roster 增删改 |
| **capabilities** | ~1610 | agent 的“手”：fs / shell / web / memory / notify / **schedule**（自建定时任务）|
| **memory** | ~1580 | 混合记忆（关键词 + 向量）、会话库、项目库、Journal、经验/偏好沉淀 |
| **core** | ~1520 | Agent 主循环（loop）、Context、prompts（含运行环境硬说明）、bootstrap 装配 |
| **channels** | ~1380 | 外部渠道（邮件为主）、配置存储 |
| **llm** | ~900 | 各 provider 适配（openai/deepseek/claude/ollama/mock）+ 重试退避 + 流式 |
| **governance** | ~650 | 声明式策略引擎（硬边界 / 确认门 / 白名单）+ Budget 预算 + 资源锁 |
| **scheduler** | ~200 | 定时任务调度循环 + 存储 |
| **observability** | ~190 | 审计日志、trace、回滚 |
| **skills** | 26 文件 | 目录化能力插件（pdf/docx/xlsx/pptx/http 等）|

## 请求主线

```
浏览器前端 (WS) / 邮件渠道
        ↓
FastAPI 服务 (server)  ——  /api REST · /ws WebSocket · 治理鉴权
        ↓
编排核心 (agents)  ［Cowork 模式强制 map-reduce DAG］
   Coordinator ──► GraphDispatcher ──► GraphOrchestrator ──► 子代理
   (Captain先自治    (map-reduce 规划)   (并发DAG·闸+重试)     researcher/
    →用尽升级)                                              executor
   core/loop = Agent 主循环（感知→规划→调用→预算），每个动作先过治理
        ↓
能力层 (capabilities + skills)
   fs · shell · web(搜索/抓取) · memory · notify(邮件) · schedule(定时) · skill 插件
        ↓
产物落工作区

横切（贯穿每一步）：governance 治理·预算 | memory 混合记忆 | llm 重试 | observability 审计/trace
```

## Mermaid 源码

```mermaid
flowchart TD
    FE["浏览器前端<br/>index.html · WebSocket"] --> SV
    ML["邮件渠道<br/>IMAP/SMTP · 白名单"] --> SV
    SV["FastAPI 服务<br/>/api REST · /ws · 治理鉴权"] --> CO
    subgraph CORE["编排核心 · agents (Cowork=强制 map-reduce DAG)"]
        CO["Coordinator<br/>Captain先自治→升级"] --> GD["GraphDispatcher<br/>map-reduce 规划"]
        GD --> GO["GraphOrchestrator<br/>并发DAG·闸+重试"]
        GO --> SUB["子代理<br/>researcher / executor"]
    end
    SUB --> CAP["能力层 capabilities + skills<br/>fs·shell·web·memory·notify·schedule"]
    CAP --> OUT["产物落工作区"]
    GOV["governance 治理·预算"] -.贯穿.- CORE
    MEM["memory 混合记忆"] -.贯穿.- CORE
    LLM["llm deepseek/claude·重试"] -.贯穿.- CORE
    OBS["observability 审计/trace"] -.贯穿.- CORE
```

## 编排可靠性说明（重要）

Cowork 模式会强制走 map-reduce DAG（研究多个对象时：轻发现 → 每对象一个并行
researcher 节点 → 串行归约落盘）。实测 **DeepSeek 在多 agent 会话并发下会持续
Connection error / timeout**，因此并发上限 `AGENT_MAX_PARALLEL` 默认 **1（串行）**：
保留分工结构，但任一时刻只有一个会话访问模型服务——这是实测唯一稳定的条件。
换用更扛并发的模型端点后，可在 `.env` 调高 `AGENT_MAX_PARALLEL`。
