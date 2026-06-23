# my-agent 项目结构全景

> 生成时间：2026-06-19 | 178 个 Python 文件 · ~21,159 行

---

## 一、项目总览

```
my-agent/                          # 项目根（~/Desktop/my agent）
├── main.py                        # ★ 入口：启动 CLI / Web
├── config.py                      # ★ 全局配置：模型/治理/记忆/简报/搜索等
├── persona.yaml                   # ★ 人格定义
├── pyproject.toml                 # 打包 & 依赖声明
├── requirements.txt               # pip 依赖
├── Makefile                       # 开发命令（setup / web / cli / docker-up）
├── Dockerfile + docker-compose.yml
├── .env.example                   # 环境变量模板
├── mcp_servers.json.example       # MCP 外部工具连接配置模板
│
├── README.md                      # 项目说明
├── PROJECT_STRUCTURE.md           # ★ 本文件：项目结构全景
├── SECURITY.md                    # 安全说明
├── RELIABILITY.md                 # 可靠性说明
├── DEPLOY.md                      # 部署指南
├── CODE_REVIEW.md                 # 代码审查
├── FRONTEND_CONTRACT.md           # 前后端契约
├── CONNECT_PHONE.md               # 手机连接说明
├── CLAUDE.local.md                # Claude 本地配置
├── PRODUCTION_READINESS.md        # 生产就绪检查
├── send_news_mail.py              # 新闻邮件发送脚本
├── LICENSE
│
├── core/                 ← 心脏层：主循环 + 启动装配 + 事件总线
├── governance/           ← ★ 治理层：安全检查的唯一收口
├── capabilities/         ← 统一能力层：工具/GUI/skill/MCP/委托
├── agents/               ← 多 Agent 编排：Coordinator / 圆桌 / 辩论 / 专家
├── channels/             ← 外部接口：CLI / Web / 邮件 / 企微 / QQ
├── server/               ← FastAPI + WebSocket 服务端
├── llm/                  ← 模型抽象层：多厂商 + Router + 流式
├── memory/               ← 记忆体系：工作记忆 + 混合长期记忆
├── observability/        ← 可观测：trace + rollback + 审计
├── scheduler/            ← 定时任务：每日简报 + 记忆清理
├── skills/               ← 插件系统：30+ 内置 skill
├── frontend/             ← Web 前端（单文件 SPA）
├── tests/                ← 回归测试（31 个文件）
├── eval/                 ← 真实模型质量评测
├── scripts/              ← 运维脚本（安装/启动/分析）
├── data/                 ← 数据文件
├── report/               ← 调研报告产出
├── logs/                 ← 运行时日志
└── uploads/              ← 上传文件
```

---

## 二、核心层 `core/` — 主循环与装配

```
core/
├── loop.py              # ★ 主循环：感知 → 规划 → 治理 → 行动 → 反思（agent 心脏）
├── bootstrap.py         # 统一装配：创建 provider / 记忆 / 能力 / 治理 / bus
├── coordinator_stack.py # Coordinator 栈：多 agent 路由入口
├── bus.py               # 事件总线：平台脊椎，单向通知 + 双向确认
├── context.py           # 上下文管理：ConversationLog + SessionAttachment
├── context_facade.py    # 对外统一 Context 接口
├── prompts.py           # 系统提示词生成（分寸原则 + 动态能力清单）
├── types.py             # 核心类型定义
├── persona.py           # 人格加载
├── captain_phase.py     # Captain 阶段标记
├── status_bar.py        # 状态栏
└── briefing.py          # 每日简报生成
```

## 三、治理层 `governance/` — ★ 分寸感所在

```
governance/
├── engine.py            # ★ 治理引擎：声明式策略 + 硬/软边界 + 裁决
├── policy.yaml          # ★ 策略声明：白名单/黑名单/确认规则/角色权限
├── base.py              # 治理基类
├── classifier.py        # 操作分类器
├── budget.py            # 金额预算控制
└── resource_lock.py     # 资源互斥锁（文件写串行化）
```

## 四、统一能力层 `capabilities/`

```
capabilities/
├── base.py              # 能力基类 + CapabilityCall 统一管线
├── delegate.py          # 子 agent 委托能力
├── escalate_dag.py      # DAG 升级编排
├── gui.py               # macOS GUI 控制（截图/点击/键入）
├── mcp_connector.py     # MCP 外部工具连接器
└── tools/               # 内置工具集
    ├── base.py          # 工具基类
    ├── fs.py            # 文件读写
    ├── shell.py         # Shell 命令执行
    ├── web.py           # 联网搜索 + 抓取
    ├── memory.py        # 记忆操作
    ├── program_memory.py# 程序记忆（KV 存储）
    ├── notify.py        # 推送通知
    └── schedule.py      # 定时任务
```

## 五、多 Agent 编排 `agents/`

```
agents/
├── coordinator.py       # ★ 主协调器：Captain → 升级专家
├── orchestrator.py      # 编排器
├── graph_orchestrator.py# DAG 图编排
├── graph_dispatcher.py  # 图调度器
├── dispatcher.py        # ★ 自动调度：选专家 + 移交上下文
├── triage.py            # ★ 分诊：判断是否需要升级 + 派给谁
├── plan_graph.py        # 计划图
├── node.py              # 图节点
├── worker.py            # ★ Worker：执行型 agent
├── worker_model.py      # Worker 模型
├── worker_prompts.py    # Worker 提示词
├── moderator.py         # 主持人（辩论/圆桌）
├── roundtable.py        # 圆桌讨论
├── debate.py            # 辩论编排
├── verifier.py          # 验证 agent
├── registry.py          # Agent 注册表
├── roster_meta.py       # 专家元数据
├── spec.py              # 编排规范
├── task_heuristics.py   # 任务启发式
├── commands.py          # 控制命令
├── base.py              # Agent 基类
├── dynamic_agents.py    # 动态 agent 创建
└── roster/              # ★ 专家配置文件
    ├── coder.yaml
    ├── executor.yaml        # 执行型 worker
    ├── researcher.yaml      # 调研型 worker
    ├── verifier.yaml
    ├── writer.yaml
    └── adler_counselor_agent.yaml
```

## 六、外部接口 `channels/`

```
channels/
├── base.py              # 渠道基类
├── cli.py               # ★ CLI 终端对话
├── cli_banner.py        # CLI 启动横幅
├── cli_prompt.py        # CLI 输入提示
├── cli_style.py         # CLI 样式
├── web.py               # Web 渠道
├── email_channel.py     # ★ 邮件渠道（收发）
├── config_store.py      # 渠道配置存储
└── task_scope.py        # 任务作用域
```

## 七、Web 服务 `server/`

```
server/
├── app.py               # ★ FastAPI + WebSocket 主程序（~65,000 行）
├── runtime_config.py    # 运行时配置 API
├── commands_api.py      # 命令 API
├── events.py            # WebSocket 事件协议
├── governance_stats.py  # 治理统计 API
├── model_keys.py        # 模型密钥管理
├── roster_api.py        # 专家管理 API
└── usage_stats.py       # 用量统计 API
```

## 八、模型层 `llm/`

```
llm/
├── factory.py           # ★ 模型工厂（按 provider 创建）
├── base.py              # LLM 基类
├── openai_llm.py        # OpenAI 兼容协议（DeepSeek 等）
├── claude_llm.py        # Claude API
├── deepseek_llm.py      # DeepSeek
├── ollama_llm.py        # 本地 Ollama
├── mock_llm.py          # Mock 模型（零依赖测试）
├── router.py            # ★ 模型路由器
├── model_registry.py    # 模型注册表
├── streaming.py         # 流式输出
└── errors.py            # 错误定义
```

## 九、记忆体系 `memory/`

```
memory/
├── base.py              # 记忆基类
├── working.py           # 工作记忆（会话内）
├── hybrid.py            # ★ 混合长期记忆入口
├── longterm_sqlite.py   # SQLite 关键词记忆
├── vector.py            # 向量语义记忆
├── ingest.py            # 记忆摄入
├── factory.py           # 记忆工厂
├── session_store.py     # 会话存储
├── journal.py           # 操作日志
├── experience_miner.py  # 经验挖掘
├── preference_miner.py  # ★ 偏好自动沉淀
├── pattern_tracker.py   # 模式追踪
├── program_store.py     # 程序记忆存储
└── project_store.py     # 项目上下文存储
```

## 十、可观测 `observability/`

```
observability/
├── base.py              # 观测基类
├── trace.py             # 调用追踪
├── rollback.py          # ★ 文件快照 + 回滚
└── audit.py             # 操作审计
```

## 十一、定时任务 `scheduler/`

```
scheduler/
├── scheduler.py         # 定时调度器（每日简报 + 记忆清理）
└── store.py             # 任务持久化存储
```

## 十二、插件系统 `skills/` — 30+ 内置能力

```
skills/
├── base.py              # Skill 基类
├── router.py            # ★ 自动路由：按任务匹配预取
├── paths.py             # Skill 路径管理
├── _guidance.py         # 指导型 skill 框架

├── claude_design/       # 落地页设计指南       [指导型]
├── design_taste_frontend/# 前端设计品味检查     [指导型]
├── email_writing/       # 邮件写作指南         [指导型]
├── meeting_notes/       # 会议纪要指南         [指导型]
├── memory_guide/        # 持久记忆使用指南     [指导型]
├── novel_creator/       # 小说创作指南         [指导型]
├── skill_author/        # 新建技能规范         [指导型]
├── weekly_report/       # 周报写作指南         [指导型]

├── csv_stats/           # CSV 数据统计          [工具型]
├── date_calc/           # 日期计算              [工具型]
├── docx_writer/         # Word 文档生成         [工具型]
├── file_append/         # 文件追加写入          [工具型]
├── file_edit/           # 文件精确替换          [工具型]
├── find_files/          # 文件查找              [工具型]
├── grep_text/           # 跨文件搜索            [工具型]
├── http_request/        # HTTP 请求             [工具型]
├── json_tools/          # JSON 格式化/校验       [工具型]
├── keyword_extract/     # 关键词提取            [工具型]
├── markdown_toc/        # Markdown 目录生成      [工具型]
├── notify_dispatch/     # 通知推送              [工具型]
├── pdf_extract/         # PDF 文本提取          [工具型]
├── personal_search/     # 个人笔记语义检索       [工具型]
├── pptx_writer/         # PPT 生成              [工具型]
├── readability_score/   # 可读性评估            [工具型]
├── table_format/        # 表格格式化            [工具型]
├── text_diff/           # 文本差异对比          [工具型]
├── text_stats/          # 文本字数统计          [工具型]
├── xlsx_writer/         # Excel 生成            [工具型]
└── ops_manual/          # 运维手册              [预留]
```

## 十三、测试 `tests/` — 31 个测试文件

```
tests/
├── harness.py                          # 测试入口
├── test_regression.py                  # ★ 回归测试（49 项）
├── test_p0_security.py                 # P0 安全测试
├── test_agent_architecture.py          # Agent 架构测试
├── test_artifacts_api.py
├── test_concurrency_retry.py
├── test_confirm.py
├── test_coworker_engine.py
├── test_dispatch_profiles.py
├── test_email.py
├── test_escalate_dag.py
├── test_executor_researcher_permissions.py
├── test_experience.py
├── test_files_api.py
├── test_graph_dag.py
├── test_journal.py
├── test_max_steps.py
├── test_mode_permissions.py
├── test_observability.py
├── test_orchestration_resilience.py
├── test_perm_model.py
├── test_plan_graph.py
├── test_policy_reload.py
├── test_project_triage.py
├── test_projects.py
├── test_roster_crud.py
├── test_runtime_env_prompt.py
├── test_schedule_capability.py
├── test_session_lazy_create.py
├── test_pattern_tracker.py
└── test_worker_model.py
```

## 十四、评测 `eval/`

```
eval/
├── harness.py           # 评测框架
├── run_real.py          # ★ 真实模型跑 10 个预置任务，LLM 评委打分
├── ws_client_test.py    # WebSocket 客户端测试
└── personal/
    └── tasks.yaml       # 预置评测任务
```

## 十五、运维脚本 `scripts/`

```
scripts/
├── launch.sh            # 启动脚本
├── install.sh / install.ps1          # 安装（macOS / Windows）
├── uninstall.sh / uninstall.ps1
├── install-autostart.sh / uninstall-autostart.sh
├── analyze.py           # 数据分析
├── rank.py              # 排序
├── final_test.py        # 综合测试
├── gen_test*.py         # 测试生成
├── debug_cli_prompt_pty.py
└── gen_final.py
```

## 十六、前端 `frontend/`

```
frontend/
├── index.html           # ★ 单文件 SPA（~306 KB）
└── README.md
```

## 十七、数据 & 产出

```
data/                              # 结构化数据
├── ai_chips_2025.csv              # AI 芯片数据
├── ev_2025.csv                    # 电动车数据
├── generated_numbers.json         # 生成数字
├── market_research_summary.md     # 市场调研摘要
├── rank_output.txt
├── trending_20260618.json         # GitHub Trending 数据
├── trending_top10.json
├── trending_top10_2026-06-18.json
├── trending_top10_new.json
├── trending_top10.docx
└── trending_top10.json.docx

report/                            # 调研报告（29 个文件）
├── ai_news_2026-06-17.md          # AI 新闻
├── analysis_01.md ~ analysis_10.md # 系列分析
├── github_trending_2026-06-18_analysis_report.md
├── trending_20260618_analysis_report.md
├── laser_interferometer_overview.md
├── agent_capability_inventory.md
├── github_trending_2025-06-18.md
├── superpowers-*.md / *.csv
├── long_task_mail_capability.md
├── executor_researcher_*_report.md
├── subagent_permissions_research.md
├── AI_API中转平台对外商业化方案汇总.docx
├── AI_API中转服务_商业化市场分析报告.md.docx
└── 给用户的一周任务邮件交付能力说明.md

logs/
├── eval_reports/    # 评测报告
├── gui_trace/       # GUI 追踪
├── reports/         # 一般报告
└── snapshots/       # 回滚快照
```

## 十八、架构速览（六层 + 脊椎）

```
channels/        外部接口（CLI / Web / 邮件 / 企微 / QQ）
    │
core/loop.py     编排器主循环（agent 心脏）
    │
core/bus.py      事件总线 ←── 平台脊椎（单向通知 + 双向确认）
    │
governance/      ★ 治理层：统一收口审查（分寸感所在）
    │
capabilities/    统一能力层（工具 / GUI / skill / MCP / 委托）
    │
memory/          记忆体系（working + hybrid）
    │
observability/   trace + rollback + audit
```

---

> **核心设计原则**
> 1. **统一能力管线**：所有操作收敛成 `CapabilityCall`，治理层只有一个收口
> 2. **安全由代码保证**：硬边界在 `governance/`，不靠 prompt
> 3. **治理三参数**：`review(call, actor, ctx)` 为多用户/多 agent 鉴权预留
> 4. **事件总线**：单向通知走 bus，双向确认走回调
> 5. **模型面向接口**：换厂商只改 `llm/factory.py`
