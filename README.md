# Captain · 你的私人专属 AI 助手

**懂你、记得你、主动找你。**

本地运行 · 数据不上云 · macOS & Windows · MIT 开源

---

## 它能做什么

**不只是聊天——Captain 会主动帮你推进事情。**

你告诉它要跟进某个客户、整理某份资料、每天早上汇报行程，它就会记住并在该出现的时候出现，不需要你反复提醒。

- **主动跟进业务进度** — 设定待跟进事项，到时间自动提醒并汇总状态
- **记住你是谁** — 记录你的职业背景、偏好、工作习惯，越用越懂你
- **一句话生成文档** — 周报 Word、汇报 PPT、数据 Excel、会议纪要，开口即出
- **帮你搜索、写作、整理文件** — 联网搜索、读写本地文件、处理 Office 文档
- **工作流模板** — 8 个常用场景预设（周报、月总结、商务邮件、请假申请…），一键套用
- **本地记忆，永久留存** — 对话记忆、工作经验、常用偏好，存在你自己机器上

---

## 一键安装

**macOS / Linux**
```bash
curl -fsSL https://irestart-your-life.club/install.sh | bash
```

**Windows**（在 PowerShell 运行）
```powershell
irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
```

安装完成后：
1. 打开 `.env` 文件，填入你的 API Key（推荐 [DeepSeek](https://platform.deepseek.com)，国内直连）
2. 双击 `captain.bat`（Windows）或运行 `captain`（macOS）启动
3. 浏览器打开 `http://localhost:8000`

> 无需 VPN，无需服务器，本地运行，数据完全在自己手里。

---

## 为什么选 Captain

| | Captain | 普通 AI 聊天 |
|---|---|---|
| 记住你的偏好和背景 | ✅ 永久记忆 | ❌ 每次重来 |
| 主动跟进代办事项 | ✅ 定时提醒 | ❌ 靠你提问 |
| 读写本地文件 | ✅ 直接操作 | ❌ 不支持 |
| 生成 Word/PPT/Excel | ✅ 一句话出成品 | ❌ 只给文字 |
| 数据存在哪里 | ✅ 你自己的电脑 | ❌ 云端服务器 |
| 费用 | ✅ 只交模型 API 费 | ❌ 按月订阅 |

---

## 支持的 AI 模型

国内直连（无需梯子）：
- **DeepSeek**（推荐）— 性价比最高，支持 deepseek-chat / deepseek-reasoner

国际模型（需梯子）：
- OpenAI（GPT-4o）
- Anthropic（Claude）
- Ollama（本地模型，完全离线）

在 `.env` 里切换，随时换模型，数据不受影响。

---

## 快速体验

```
你：帮我每周五下午 5 点，整理本周工作内容发给我
Captain：好的，我会在每周五 17:00 自动整理并发送周报给你。
         请问发到哪个邮箱？

你：需要跟进一下张总的合同，三天后提醒我
Captain：已记录。我会在 2025-01-18 提醒你跟进张总的合同。
```

---

## 版本与定价

**Free 版**（永久免费）
- 无限对话
- 文件读写、联网搜索
- 工作流模板
- 本地记忆

**Pro 版**（一次性买断）
- 所有 Free 功能
- 主动任务跟进与定时提醒
- 高级工作流（自动发邮件、生成文档）
- 优先支持

[→ 购买 Pro 授权码](https://irestart-your-life.club/#pricing)

---

## 本地开发

```bash
git clone https://github.com/john-lcj/my-agent
cd my-agent
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
pip install -r requirements.txt
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

开发时设 `CAPTAIN_DEV_PRO=1` 跳过授权检查。

---

## 架构概览

```
server/       FastAPI + WebSocket 后端
frontend/     纯原生 JS 前端（无框架依赖）
capabilities/ 40+ 内置能力（文件/搜索/浏览器/Git/日历/Office…）
memory/       本地 SQLite 长期记忆
scheduler/    定时任务引擎
skills/       内置工作流模板
```

单进程、单 Agent、顺序执行。本地优先，数据不离机。

---

许可证：[MIT](LICENSE) · 安全说明：[SECURITY.md](SECURITY.md)
