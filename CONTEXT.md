# Captain 项目对话传承文档
> 最后更新：2026-06-29

---

## 项目概况

**产品名**：Captain — 私人专属 AI Agent 平台  
**定位**：本地运行、数据不上云、懂你记得你主动找你  
**工作目录**：`/Users/luchangjie/Desktop/my agent`  
**GitHub**：`https://github.com/john-lcj/my-agent`  
**GitHub 推送**：使用本机 GitHub 凭据或临时 token；不要把 token 写入文档或提交历史。

**线上服务**：
- Landing Page + License Server：`https://irestart-your-life.club`
- License Server 部署在 VPS，Docker Compose，路径 `/opt/license_server/`

---

## 技术架构

- **后端**：FastAPI + WebSocket，`python -m uvicorn server.app:app --host 127.0.0.1 --port 8000`
- **前端**：纯原生 JS（无框架），`frontend/index.html` + `frontend/app.js` + `frontend/styles.css`
- **存储**：SQLite（对话/记忆）+ JSON 文件（goals/monitors）存于 `data/`
- **授权**：本地 XOR 缓存 `~/.captain/.license_cache`，验证服务 `license.irestart-your-life.club`
- **开发绕过授权**：`CAPTAIN_DEV_PRO=1`
- **persona 文件**：`persona.yaml`（owner 段存用户档案）
- **版本文件**：`VERSION`（当前 `0.1.0`）
- **错误日志**：`logs/error.log`

---

## 关键文件清单

| 文件 | 说明 |
|------|------|
| `server/app.py` | 主后端，所有 API 端点 |
| `frontend/index.html` | 完整前端 HTML |
| `frontend/app.js` | 前端逻辑（约4700行） |
| `frontend/styles.css` | 样式，含移动端适配 |
| `install.sh` | macOS/Linux 一键安装 |
| `install.ps1` | Windows Portable 安装（当前正在调试） |
| `main.py` | 启动入口，含 error log 初始化 |
| `persona.yaml` | 用户档案（owner 段） |
| `VERSION` | 版本号 `0.1.0` |
| `landing/index.html` | 产品介绍页 |
| `landing/wechat-pay.jpg` | 微信收款码 |
| `license_server/` | 授权服务器（VPS 上运行） |
| `license_server/admin_cli.py` | 管理员 CLI，gen/send 命令 |
| `license_server/.env` | SMTP 配置（本地，不进 git） |
| `data/goals.json` | 目标数据（新增） |
| `data/monitors.json` | 监控数据（新增） |

---

## 已完成功能

### 核心功能
- 单 Agent 顺序执行循环
- FastAPI + WebSocket 流式输出
- 40+ 内置能力（文件/搜索/浏览器/Git/邮件等）
- 混合长期记忆（SQLite 关键词 + 向量语义）
- 治理层（风险分级、声明式策略）

### 商业化
- License Key 生成/激活/验证（Free/Pro）
- 本地授权缓存（XOR 混淆）
- 应用内激活 UI（关于页）
- 手动发码流程：微信收款 → 客户发邮件截图 → `admin_cli.py gen` + `send`

**完整发码命令**（在 `license_server/` 目录）：
```bash
# 生成授权码
python admin_cli.py gen --plan pro --days 365 --note "客户姓名"
# 发送邮件
python admin_cli.py send --key CAPT-PRO-XXXX-XXXX-XXXX --to 客户邮箱
```
SMTP 配置：QQ 邮箱 `852420621@qq.com`，授权码 `jljnazhtexldbcif`

### 产品功能
- **用户档案**：`persona.yaml` owner 段，API `/api/profile` GET/POST
- **工作流模板**：8个预设（每日简报/邮件/文件整理/会议纪要/研究/代码/数据/定时任务）
- **目标管理**：`/api/goals` CRUD，存 `data/goals.json`
- **变化监控**：`/api/monitors` CRUD，存 `data/monitors.json`
- **版本显示**：`/api/version` 读 VERSION 文件
- **一键更新**：`/api/system/update`，git fetch + reset + pip install + 自动重启
- **移动端 UI**：iOS safe area、16px 输入字体、44px 触控目标

### Windows 支持
- `install.ps1`：Portable Python 3.11 + PortableGit 2.45.2，无需预装任何环境
- 安装后桌面生成 `Captain.lnk` 快捷方式
- `captain_launch.vbs`：检测服务是否运行 → 启动 bat → 自动打开浏览器
- `captain.bat`：设置 PATH 并启动 uvicorn

**Windows 安装命令**（PowerShell）：
```powershell
irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
```

**macOS/Linux 安装命令**：
```bash
curl -fsSL https://irestart-your-life.club/install.sh | bash
```

---

## 当前待解决问题

### Windows install.ps1（最近一直在调试）
最新状态（commit `7cd0717`）：

**已修复**：
1. ✅ 闪退 → 末尾加 ReadKey
2. ✅ 需要梯子 → Portable Python（华为云）+ PortableGit（npmmirror）+ 清华 pip
3. ✅ git 检测误判 → 改用 Get-Command + 刷新 PATH
4. ✅ 目录非空 clone 失败 → 改用 git init + fetch + reset
5. ✅ git stderr hint 触发 Stop → 去掉 ErrorActionPreference=Stop
6. ✅ captain.bat 乱码 → ASCII 编码写入（去 BOM）
7. ✅ No module named uvicorn → 修复 `_pth` 文件逐行处理 + 创建 site-packages 目录
8. ✅ VBS 语法错误（未结束字符串）→ 改用 here-string 生成 VBS
9. ✅ 检查更新 git 启动失败 → subprocess 传入 git bin 目录到 PATH（PortableGit 需要自己的 DLL）

**用户刚报告**（最后两条，commit 已推送但未确认验证）：
- VBS 点击报"未结束的字符串常量"→ 已用 here-string 修复，待客户验证
- 检查更新"error launching git"→ 已加 git_env PATH，待客户验证

### 前端 bug（commit `43bb964` 已修复）
- ✅ 工作流模板点击无效：`getElementById('composer-input')` → `getElementById('chat-inp')`
- ✅ 我的档案保存报错：`open(persona.yaml, 'r')` 文件不存在 → 先判断再创建
- ✅ 目标/监控"加载失败"：端点不存在 → 已新增 `/api/goals` `/api/monitors`
- ✅ 检查更新 pip 路径错误：`.venv/bin/pip`（macOS）→ 自动探测 portable/venv/sys

---

## .gitignore 重要规则（安全）

绝不进 git：
- `.env`（SMTP 密钥等）
- `*.pem`
- `scripts/`（含阿里云硬编码 key）
- `*.github_token`
- `logs/`、`uploads/`、`demo/`、`收件箱/`

---

## VPS 待办（用户需手动操作）

1. 上传最新 `landing/index.html` 到 VPS
2. SSH 到服务器，在 `/opt/license_server/.env` 添加 SMTP 配置：
```
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=852420621@qq.com
SMTP_PASS=jljnazhtexldbcif
SMTP_FROM=852420621@qq.com
```
然后 `docker compose restart`

---

## 近期对话重点

本次会话主要围绕 **Windows install.ps1 调试**，经历了多轮迭代：
- 从 winget 方案 → Portable 方案（根本性改变）
- Portable 方案遇到：目录非空/git hint/BOM 乱码/site-packages/VBS 语法/PortableGit DLL 等问题
- 每次都是客户在 Windows 上实际测试后反馈报错

另外修复了已有客户发现的前端/后端 bug（目标、监控、工作流模板、档案、更新）。

---

## 下一步建议

1. **验证** Windows 桌面图标和检查更新是否正常（等客户反馈）
2. **macOS install.sh** 同样可考虑做 Portable/自包含方案
3. **VPS SMTP** 配置（用户还没做）
4. **landing 页** 上传到 VPS
5. 后续功能：主动跟进提醒（Pro 功能）、多用户支持
