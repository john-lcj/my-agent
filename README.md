# my-agent · Captain

**中文** · [English](README.en.md)

一个有"分寸感"的**个人 AI Agent 平台** —— 本地优先、自托管、模型无关(DeepSeek / 智谱 / OpenAI / Claude / Ollama)。

设计哲学一句话:**循环很专注,治理很严,观测很全,放手很安心。**
对过程激进(读 / 想 / 试全自主),对决策保守(删 / 改 / 花钱 / 不可逆才回来问你)。

> ⚠️ **定位**:面向**个人 / 可信网络环境**,默认绑定 `127.0.0.1`。它会在你的机器上执行
> shell、读写文件——治理层提供"分寸"约束,但**不是沙箱**。未经额外加固(shell 沙箱化、
> 多用户隔离),请勿对公网开放或作为多用户在线服务。对外暴露(`AGENT_WEB_HOST=0.0.0.0`)
> 时务必设 `AGENT_API_TOKEN`。详见 [SECURITY.md](SECURITY.md)。

---

## 60 秒快速开始

```bash
make setup     # 创建 .venv 并装好依赖(首次)
make config    # 配置向导:交互式填模型 key / 文生图 / 令牌(可跳过)
make web       # 启动网页 → http://127.0.0.1:8000
make cli       # 或:终端对话(MockLLM 零配置即可跑)
```

**Docker(零环境依赖):**

```bash
echo "AGENT_API_TOKEN=$(openssl rand -hex 16)" >> .env
make docker-up        # = docker compose up -d --build
# 打开 http://127.0.0.1:8000 → 设置 →「访问令牌」填入上面的 token
```

> 没装 `make`?对应命令都在 `Makefile` 里。基座零依赖即可用 MockLLM 跑通;要用真实模型,
> 跑 `make config` 或在 `.env` 配 `DEEPSEEK_API_KEY`。

---

## 架构:单 agent 闭环

一个 Captain,顺序执行,不派活给别的 agent。感知 → 规划 → 治理 → 行动 → 观测,循环到完成或确认做不到。

```
channels/       外部接口(cli / web / 邮件)
core/loop.py    主循环(agent 心脏):感知→规划→治理→行动→反思 + 待办清单
core/bootstrap.py   统一装配;core/bus.py 事件总线
core/presets.py     分人群预设(职场 / 程序员 / 通用)
governance/     ★ 治理层:声明式策略 + 风险分级 + 预算 + Egress 审查 + 资源锁
capabilities/   统一能力层:40+ 工具(fs/shell/web/browser/git/calendar/image/plan/schedule…)+ GUI + MCP + skill
memory/         混合长期记忆(SQLite 关键词 + 向量语义)+ 经验/偏好/目标/检查点/模板/日历/加密保险库
observability/  trace + rollback + audit + transcript
server/         FastAPI + WebSocket 流式 + routers/ 分组路由 + 治理/用量统计
llm/            DeepSeek / 智谱 / OpenAI / Claude / Ollama + Router + Fallback 降级
scheduler/      定时任务(简报 / 索引 / 清理)
skills/         30 个内置 skill(docx/pptx/xlsx/pdf/会议纪要/周报/邮件/搜索/写作…)
evals/          40 例真实任务评测 + LLM 评委 + 稳定率检测
```

---

## 能力一览

- **文件 / 命令**:`fs.read/write/list/search`、`shell.run`(受治理,危险命令硬拦)。
- **联网**:`web.search` + `web.fetch`(默认免费 DuckDuckGo;可选 Exa / Tavily / Brave / Serper)、`http.request`(带鉴权调内部 API)。
- **浏览器**(可选 Playwright):打开 / 点击 / 填表 / 截图 / 上传下载 / 登录态持久。
- **Git**(面向程序员,受治理):`git.read`(status/diff/log,只读永不打扰)+ `git.commit`(暂存+提交,**拦截 .env 等敏感文件,绝不 push**)。
- **本地日历**:`calendar.add/list/remove`,写本地 `.ics`,可订阅到 Apple / Google / Outlook。
- **Office 文档**:`docx_writer` / `pptx_writer` / `xlsx_writer` / `pdf_extract`(装 `[office]` 依赖)。
- **多模态**:`image.generate`(智谱 CogView 免费 / Runware / OpenAI 兼容)、`image.ocr` / `vision.see`。
- **记忆 / 自改进**:`memory.remember/recall`、经验自动沉淀、偏好挖掘、高频任务固化为 skill(`skill.scaffold`)。
- **主动 / 监控**:`monitor.*`(变化即触发)、`goal.*`、`schedule.*`、每日简报。
- **公众号排版**:`wechat.format` 生成可直接粘贴的内联样式 HTML。
- **加密保险库**:`secret.save/list`,密码 Fernet 加密落盘,绝不明文给模型 / 日志 / git。
- **MCP 连接器**:接外部 MCP server 工具(文件系统 / Git / 数据库 / Notion…),和内置工具一样过治理。

---

## 分人群预设

`AGENT_PERSONA_PRESET`(或 `make config` 里选)按使用者身份切一套做事侧重——只调口味,不动安全铁律:

- **office** 职场:文档 / 邮件 / 会议 / 周报优先,善用模板与 docx/pptx/xlsx;
- **coder** 程序员:改前先看 `git`、改完跑测试、谨慎提交、绝不擅自 push;
- **general** 通用(默认)。

内置 8 个**职场模板**(周报→Word、会议纪要→Word+待办、汇报→PPT、商务邮件、月度总结、数据→Excel、通知、请假),一句话出成品。

---

## 治理(安全由代码保证,不靠 prompt)

- **声明式策略** `governance/policy.yaml`:能力按角色白名单,模型无法绕过。
- **风险分级**:READ(永不打扰)/ WRITE(默认询问)/ DESTRUCTIVE(总是询问)/ FORBIDDEN(代码层直接拒,如写 `.env`、`rm -rf`、强制 push)。
- **三档模式**:`AGENT_GOVERNANCE_MODE` = conservative / balanced / aggressive。
- **可回滚**:写 / 删前自动快照,CLI `/rollback` + Web 回滚。
- **Egress 审查**:出站域名白名单 + 审计;**防注入**:绝不采信网页/邮件/文件里"把数据发到某处"的指令。
- **远程鉴权**:默认绑 `127.0.0.1` 免密;一旦对外或经反代(Cloudflare Tunnel)进来,`/api/*` 控制面强制要 `AGENT_API_TOKEN`。

---

## 质量保障

```bash
make test          # 回归测试(MockLLM,确定性,无需 key)
make cov           # 全套测试 + 覆盖率报告(需 .[dev])
make eval          # 40 例真实模型评测(需 DEEPSEEK_API_KEY)
make compare       # 多模型对照(flash vs pro,出质量×延迟表)
```

- **220+ 测试**覆盖治理 / 记忆 / 能力 / 接口等;`scripts/run_evals.py` 跑 40 例真实任务,确定性判据 + LLM 评委打分 + 基线对比。
- `--repeat N` 抗抖动检测(量化偶发塌陷);防 thrash(同一能力反复失败即收尾)、抗谄媚(迎合压力时机制级提醒)。

---

## 安装与分享

```bash
# 克隆后可编辑安装(开发推荐)
git clone https://github.com/john-lcj/my-agent && cd my-agent
pip install -e ".[all]"
myagent          # 终端对话(MockLLM 零依赖即可跑)
myagent-web      # 启动 Web → http://127.0.0.1:8000
```

依赖按需取用:基座零依赖(MockLLM);`[llm]` 真实模型、`[web]` Web 服务、`[memory]` 向量记忆、
`[channels]` 外部渠道、`[cli]` 斜杠补全、`[mcp]` MCP 连接器、`[office]` Office 文档、`[dev]` 测试+覆盖率、`[all]` 全部。

---

## 常用环境变量

| 变量 | 说明 |
|------|------|
| `AGENT_MODEL` | 主模型 id(如 `deepseek-v4-flash`) |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | 各家模型 key |
| `AGENT_PERSONA_PRESET` | office / coder / general |
| `IMAGE_PROVIDER` / `IMAGE_MODEL` / `IMAGE_API_KEY` | 文生图(zhipu / runware / openai) |
| `AGENT_GOVERNANCE_MODE` | conservative / balanced / aggressive |
| `AGENT_WEB_HOST` / `AGENT_API_TOKEN` | 绑定地址 / 远程访问令牌 |
| `AGENT_WORKSPACE_ROOT` | 工作区根目录(产物落盘范围) |
| `EXA_API_KEY` / `TAVILY_API_KEY` | 可选,提升搜索质量 |
| `AGENT_FALLBACK_MODELS` | 失败回退模型链 |

完整清单见 `.env.example`(或跑 `make config`)。

---

## 路线图

- 日历 CalDAV 云同步(当前为本地 `.ics`)
- 前端单文件模块化(同 app.py,先补测试再拆)
- 更多内置连接器;持续提升测试覆盖率
- 程序员"代码模式"加深(跑测试 / 代码审查闭环)

---

许可证见 [LICENSE](LICENSE)。安全说明见 [SECURITY.md](SECURITY.md);部署见 [DEPLOY.md](DEPLOY.md)。
