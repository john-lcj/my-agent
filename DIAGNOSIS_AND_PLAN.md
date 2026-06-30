# Captain 全面诊断 + 优化计划 + 更新路线图

> 诊断时间：2026-06-29
> 诊断范围：Windows / macOS / Linux 兼容性、现阶段 bug、安全与可维护性
> 用途：交付给下一个对话直接实施。每条问题都给出 **文件:行号 / 症状 / 根因 / 修复方案 / 验收标准**。
> 说明：本文件基于对真实代码库（非 CONTEXT.md）的逐文件审查得出。

---

## 0. 项目现状总览

Captain 实际体量远超 `VERSION` 标注的 `0.1.0`，是一个结构完整、模块清晰的本地单 Agent 平台：

- **源码规模**：约 140 个 Python 源文件（已排除 `.venv`/`uploads`/缓存）。
- **核心分层**：`core/`（循环、调度、persona、prompts）、`capabilities/tools/`（28 个工具：fs/shell/git/web/browser/email/calendar/memory/notify…）、`llm/`（8 个 provider + router + fallback）、`memory/`（25 个 store，含 sqlite + 向量混合记忆）、`governance/`（风险分级/预算/出网控制）、`channels/`、`skills/`（24 个内置 skill）、`server/`（FastAPI + routers）、`license_client`/`license_server`、`scheduler/`、`observability/`。
- **前端**：`frontend/app.js` 约 4989 行原生 JS；`server/app.py` 单文件 2346 行（端点以闭包形式定义在 `create_app()` 内）。

**结论**：底子很扎实，离“完全体”的差距不在功能广度，而在**跨平台安装/启动/更新链路的可靠性**与**少量数据安全/隐私问题**。下面按严重程度排序。

---

## 1. P0 — 致命问题（不修则新装用户用不起来 / 会丢数据）

### P0-1　macOS / Linux 启动器根本不会启动服务
- **文件**：`server/app.py`（全文件无 `if __name__ == "__main__"`）；`install.sh:180-189`（`create_launcher` 生成 `captain.sh`，内容为 `exec python server/app.py`）；`install.sh:205-229`（launchd plist 同样调用 `python server/app.py`）。
- **症状**：macOS/Linux 用户按 install.sh 安装后，运行 `bash captain.sh`，进程瞬间退出，浏览器打开 `http://localhost:xxxx` 连不上。
- **根因**：`server/app.py` 末尾只定义了 `run()` 函数和模块级 `app = create_app()`，但**没有任何代码调用 `run()`**。`python server/app.py` 仅导入模块、构造 `app`、随即正常退出（exit 0），uvicorn 从未启动。CONTEXT 里能跑是因为开发时手动用 `python -m uvicorn server.app:app`。
- **修复**：二选一（建议都做）：
  1. 在 `server/app.py` 末尾追加：
     ```python
     if __name__ == "__main__":
         run()
     ```
  2. 同时把 `install.sh` 的 launcher 改为更稳的模块调用：
     ```bash
     exec python -m uvicorn server.app:app --host 127.0.0.1 --port "${AGENT_WEB_PORT:-8000}"
     ```
     launchd plist 的 `ProgramArguments` 同步改成 `-m uvicorn ...`。
- **验收**：在干净 macOS 上跑 `bash install.sh` → `bash ~/captain/captain.sh`，浏览器能打开聊天界面；`curl -s localhost:<port>/healthz` 返回 200。

### P0-2　端口配置三套并存、互相打架
- **文件**：`server/app.py:2344`（真正读 `AGENT_WEB_PORT`，默认 8000）；`install.sh:168`（`.env` 写 `AGENT_PORT=8765`）、`install.sh:276`（提示用户开 `:8765`）；`install.ps1:169`（`.env` 写 `AGENT_PORT=8000`）、`install.ps1:185`（captain.bat 硬编码 `--port 8000`）、`install.ps1:206,212`（VBS healthz/打开用 `:8000`）。
- **症状**：macOS 上即便修好 P0-1，服务实际监听 8000，而安装脚本告诉用户开 8765 → 打不开。Windows 三处都是 8000，仅因巧合一致；`.env` 里的 `AGENT_PORT` 在所有平台都是**死配置**（没人读）。
- **根因**：服务读 `AGENT_WEB_PORT`，而安装脚本写/用 `AGENT_PORT` 或硬编码，变量名不统一。
- **修复**：统一为单一变量 `AGENT_WEB_PORT`（默认 8000）。
  - `.env` 模板：`AGENT_WEB_PORT=8000`（删除 `AGENT_PORT`）。
  - `install.sh` 的 launcher、print_done 提示、launchd/systemd 全部用 `${AGENT_WEB_PORT:-8000}`。
  - `install.ps1` 的 captain.bat 用 `--port %AGENT_WEB_PORT%`（从 .env 或默认 8000 读取），VBS 的 healthz/打开 URL 用同一端口。
- **验收**：改任意平台 `.env` 的 `AGENT_WEB_PORT=9000`，重启后服务监听 9000，桌面图标/提示打开的也是 9000。

### P0-3　“一键更新”杀掉服务后在任何平台都不会自动重启
- **文件**：`server/app.py:1200-1209`（更新成功后 `os.kill(SIGTERM)` / `os._exit(0)`）；Windows `install.ps1:177-190`（captain.bat 末尾仅 `pause`，无重启循环）；macOS `install.sh:223`（launchd `KeepAlive=false`、`RunAtLoad=false`）；Linux `install.sh:249`（systemd `Restart=on-failure`）。
- **症状**：用户在“关于/系统”里点“检查更新”，更新拉取成功后服务直接消失，再也起不来；macOS 上还叠加 P0-1（手动重启也启动不了）。
- **根因**：更新端点假设外部有 supervisor 会拉起进程，但三个平台的启动方式都不满足：bat 不循环、launchd 不保活、systemd 只在**异常退出**时重启（SIGTERM 是 0 号正常退出，不触发）。
- **修复**（推荐组合）：
  1. 更新端点不要“杀进程等别人拉起”，改为**先 spawn 一个分离的重启进程，再退出**（跨平台）：
     - Unix：`subprocess.Popen([sys.executable, "-m", "uvicorn", ...], start_new_session=True)` 后再退出旧进程；或写一个 `relaunch` 脚本。
     - 或更简单：让启动器自带重启循环（见下）。
  2. 启动器自带 supervisor：
     - Windows captain.bat 用 `:loop` … `goto loop` 循环重启 uvicorn。
     - macOS launchd 改 `KeepAlive=true`（或仅在更新场景下临时 load）。
     - Linux systemd 改 `Restart=always`。
  3. 前端更新成功后给出“正在重启，约 5 秒后自动刷新”的轮询 `/healthz` 重连逻辑。
- **验收**：点“检查更新”（确有新 commit），更新后 10 秒内服务自动回到可用，前端自动重连。

### P0-4　更新用 `git reset --hard` 会清空用户已保存的个人档案（数据丢失）
- **文件**：`server/app.py:1115-1116`（`/api/profile` 把 owner 的 name/about/preferences 写入 `persona.yaml`）；`persona.yaml`（**被 git 跟踪**，见 `git ls-files`）；`server/app.py:1188-1191` 与 `install.ps1:123,131`（更新时 `git reset --hard FETCH_HEAD`）。
- **症状**：用户在“我的档案”里填了资料 → 某次点“检查更新” → `reset --hard` 用远程版本覆盖 `persona.yaml` → 档案被清空。
- **根因**：把**用户运行期数据**存进了 **git 跟踪的源码文件**，而更新策略是强制 reset。
- **修复**：
  1. 把 owner 档案从 `persona.yaml` 迁出到**非跟踪**位置，如 `data/owner.json`（`data/` 已在 `.gitignore`）或 `~/.captain/owner.json`。`load_persona` 读取时合并：源码 `persona.yaml`（仅 agent 人设）+ 用户档案文件（owner 段）。
  2. 从 git 移除 `persona.yaml` 对 owner 段的承载：`git rm --cached` 不现实（agent 段仍需入库），所以采用“分文件”方案——`persona.yaml` 只留 `agent:` 段并保持跟踪，owner 段独立存非跟踪文件。
  3. 更新前对任何可能被用户改动的跟踪文件做 `git stash`（兜底），reset 后再 `stash pop`（冲突则保留用户版）。
- **验收**：填写档案 → 触发更新 → 档案仍在；`data/owner.json` 不随 git 变化。

---

## 2. P1 — 高优先级（影响 Windows 用户 / 隐私 / 安装成功率）

### P1-1　`AGENT_PERSONAL_DIRS` 与额外 skill 目录在 Windows 上被冒号切碎
- **文件**：`config.py:87`（`AGENT_PERSONAL_DIRS ... .split(":")`）；`skills/paths.py:25`（`AGENT_SKILLS_DIRS ... extra.split(":")`）。
- **症状**：Windows 路径 `C:\Users\me\docs` 会在盘符冒号处被切成 `C` 和 `\Users\me\docs`，个人数据接入与额外 skill 目录在 Windows 上静默失效。
- **修复**：把 `.split(":")` 改为 `.split(os.pathsep)`（Windows 为 `;`，Unix 为 `:`）。两处都改。
- **验收**：Windows 上设 `AGENT_PERSONAL_DIRS=C:\a;D:\b`，`Config.PERSONAL_DIRS` 解析为两条完整路径。

### P1-2　隐私：`persona.yaml` 被提交进（公开）GitHub 仓库
- **文件**：`persona.yaml`（`git ls-files` 显示已跟踪）；仓库 `https://github.com/john-lcj/my-agent` 为公开仓库。
- **症状**：当前 owner 段为空尚无泄露；但设计上一旦用户填了档案并 push，个人信息进入公开仓库。
- **修复**：随 P0-4 一并处理——owner 档案迁出跟踪文件后，确保 `persona.yaml` 不再含个人数据；如有历史提交含隐私，考虑 `git filter-repo` 清史（按需）。
- **验收**：`git ls-files | grep persona` 仅含 agent 人设，无任何个人字段。

### P1-3　更新时 pip 不走国内镜像 → 国内用户更新慢/失败且被静默吞掉
- **文件**：`server/app.py:1196-1199`（`pip install -r req`，无 `-i` 镜像，且 `capture_output=True` 不检查 returncode）；对比 `install.ps1:142`、`install.sh:129` 都用了镜像。
- **症状**：更新拉到新代码后装依赖直连 PyPI，国内极慢或超时；失败也不报错，用户得到“更新成功”但依赖其实没装上 → 下次启动 ImportError。
- **修复**：更新端点的 pip 命令复用安装时的镜像（可从环境变量 `PIP_INDEX_URL` 或常量读取），并检查 returncode、把失败回传前端。
- **验收**：断开 PyPI 直连、仅留镜像，更新仍能成功装依赖；镜像也失败时前端显示明确错误。

### P1-4　`requirements.txt` 一股脑装重依赖；Playwright 内核从不下载
- **文件**：`requirements.txt`（playwright/tiktoken/pdfplumber/numpy/sqlite-vec 等全列为必装，注释却说“用哪个装哪个”）；`install.ps1:142`、`install.sh:131`（`pip install -r requirements.txt` 全量装）；无任何 `playwright install chromium`。
- **症状**：Windows 嵌入式 Python 全量装这些包耗时长、体积大；且 `browser.*` 工具运行时报“需下载内核”，用户困惑。
- **修复**：
  1. 拆分 `requirements-base.txt`（fastapi/uvicorn/websockets/openai/PyYAML 等运行最小集）+ 可选组（`[browser]`/`[office]`/`[memory]`），安装脚本默认只装 base。
  2. 重依赖按需懒加载并给清晰提示（部分已如此）。
  3. 若保留 browser 能力，安装末尾可选执行 `python -m playwright install chromium`（带询问/超时兜底）。
- **验收**：默认安装在 2 分钟内完成；不装 browser 组时核心聊天/文件/搜索全部可用。

### P1-5　依赖完全没有锁版本；开发用 3.14、分发用 3.11 嵌入版
- **文件**：`requirements.txt`（全部 `>=`，文末提到 freeze 命令但**未附 lock 文件**）；`.venv` 为 Python `3.14`，`install.ps1:18` 分发 Python `3.11.9` 嵌入版。
- **症状**：某次 `pip install` 或更新可能拉到 fastapi/uvicorn/openai 的破坏性新版本，导致线上随机崩；3.14 与 3.11 行为/wheel 差异带来“我这能跑客户不能跑”。
- **修复**：在跑通环境 `pip freeze > requirements.lock.txt` 并随仓库分发；安装/更新优先用 lock。统一声明支持的 Python 区间（建议 3.10–3.12），在该区间做 CI。
- **验收**：两台机器按 lock 安装得到完全一致的依赖版本；3.11 与 3.12 各跑一遍冒烟测试通过。

---

## 3. P2 — 中等（健壮性与安全加固）

### P2-1　本机免密 = 任意本地进程/恶意网页可驱动 Agent（DNS rebinding / CSRF）
- **文件**：`server/app.py:753-766`（`_api_auth`：loopback 一律免密）；全局未见 `CORSMiddleware`、未校验 `Host`/`Origin`。
- **症状/风险**：用户浏览器访问的恶意网页可向 `http://localhost:8000/api/...` 发请求触发 Agent 的 shell/fs/browser 能力（响应被 CORS 拦截读不到，但**副作用已执行**）。对一个具备命令执行能力的本地 Agent，这等于本地 RCE 面。
- **修复**：
  1. 校验 `Host` 头必须是 `localhost`/`127.0.0.1[:port]`，否则拒绝（挡 DNS rebinding）。
  2. 对“写/执行类”端点校验 `Origin` / `Sec-Fetch-Site: same-origin`，或即便 loopback 也要求 `X-Agent-Token`。
  3. 显式加 CORS 策略（默认禁跨域）。
- **验收**：构造一个 `Origin: http://evil.com` 的 POST 到 `/api/...` 被拒；正常前端不受影响。

### P2-2　`AUTH_SECRET` 默认是硬编码常量
- **文件**：`server/auth.py:20`（默认 `captain-dev-secret-change-me-in-prod`）。
- **症状/风险**：若部署（尤其文档推广的手机/Tailscale 远程访问）未设 `AUTH_SECRET`，JWT 可被伪造。
- **修复**：安装时生成随机 `AUTH_SECRET` 写入 `.env`；远程模式（非 loopback / 经代理）下若检测到默认值则拒绝服务并提示。
- **验收**：新装机 `.env` 含随机 `AUTH_SECRET`；默认值下开远程访问被拒。

### P2-3　`os.kill(SIGTERM)` 自重启机制脆弱
- **文件**：`server/app.py:1206`。
- **说明**：随 P0-3 一并重构（用 spawn 分离进程或 supervisor 循环），不要依赖“自杀 + 别人拉起”。

### P2-4　`server/app.py` 2346 行巨型单文件
- **文件**：`server/app.py`（端点以闭包定义于 `create_app()`，已有 `server/routers/` 但大量逻辑仍内联）。
- **症状**：难测试、难维护、合并冲突高发。
- **修复**：渐进式把 channels/tasks/system/profile/license 等端点迁到 `server/routers/`，闭包内仅做依赖装配。非阻塞，可分批。
- **验收**：`server/app.py` 降到合理体量（如 < 800 行），路由按域拆分，现有测试全绿。

---

## 4. P3 — 打磨项（体验/一致性）

| 编号 | 文件:行 | 问题 | 修复 |
|------|---------|------|------|
| P3-1 | `install.sh:55` | `detect_python` 用 `MAJ -ge 3` 会误收 4.x | 显式限定 `MAJ==3 且 10<=MIN<=12` |
| P3-2 | `config.py:51` vs `.env` 模板 | 默认 DeepSeek 模型 `deepseek-v4-flash` 与模板 `deepseek/deepseek-chat` 不一致 | 核对 `llm/model_registry` 实际 id，统一默认，避免首启“未知模型” |
| P3-3 | `install.ps1:154-171` vs `install.sh:143-175` | 两边 `.env` 模板字段不一致（Win 缺 `ANTHROPIC_API_KEY`、变量名不同） | 统一 `.env` 模板（同字段、同变量名、同默认端口） |
| P3-4 | `install.sh:195` | macOS 软链写死 `/usr/local/bin`（Apple Silicon 应为 `/opt/homebrew/bin`） | 用 `$(brew --prefix)/bin` 或跳过 |
| P3-5 | `install.ps1:210` VBS | 启动后固定 `Sleep 3500` 才打开浏览器，慢机器会先打开空白页 | 改为轮询 `/healthz` 直到 200 再打开 |
| P3-6 | `install.ps1` 控制台输出 | Emoji/制表符在 cp936 旧 PowerShell 可能乱码 | 开头设 `[Console]::OutputEncoding=[Text.Encoding]::UTF8` 或纯 ASCII |
| P3-7 | `requirements.txt` 注释 | 文末提到 lock 但未附 | 见 P1-5 |

---

## 5. 跨平台测试矩阵（“完全体”验收必跑）

| 场景 | Windows 10/11 | macOS (Intel) | macOS (Apple Silicon) | Linux (apt) |
|------|---------------|---------------|------------------------|-------------|
| 干净机一键安装 | ☐ | ☐ | ☐ | ☐ |
| 启动器能拉起服务并打开浏览器 | ☐ | ☐ | ☐ | ☐ |
| 端口可由 `.env` 配置且一致 | ☐ | ☐ | ☐ | ☐ |
| 填写个人档案 → 重启后仍在 | ☐ | ☐ | ☐ | ☐ |
| 点“检查更新” → 自动重启回到可用 | ☐ | ☐ | ☐ | ☐ |
| 更新后个人档案不丢 | ☐ | ☐ | ☐ | ☐ |
| `AGENT_PERSONAL_DIRS` 多路径生效 | ☐ | ☐ | ☐ | ☐ |
| 核心聊天/文件/搜索（不含 browser）可用 | ☐ | ☐ | ☐ | ☐ |
| browser.* 安装 chromium 后可用 | ☐ | ☐ | ☐ | ☐ |
| 恶意 Origin 的 /api 请求被拒 | ☐ | ☐ | ☐ | ☐ |

---

## 6. 实施路线图（建议分支与节奏）

**Phase 0 — 紧急热修（1 个 PR，当天）**
P0-1（app.py `__main__` + launcher 用 `-m uvicorn`）、P0-2（统一 `AGENT_WEB_PORT`）、P0-4（档案迁出跟踪文件）。这三项决定“新装用户能不能用、会不会丢数据”，必须最先合并。

**Phase 1 — 更新链路与 Windows 修复（1-2 个 PR）**
P0-3（更新自重启 + 启动器 supervisor）、P1-1（`os.pathsep`）、P1-3（更新走镜像 + 校验）、P1-4（依赖拆分 + playwright 处理）、P1-5（lock 文件 + Python 区间）。

**Phase 2 — 安全加固（1 个 PR）**
P2-1（Host/Origin 校验、CORS）、P2-2（随机 AUTH_SECRET）、P1-2（persona 隐私收尾）。

**Phase 3 — 可维护性与打磨（持续）**
P2-4（app.py 拆 routers）、全部 P3 项、补 CI 跑测试矩阵。

**“完全体”定义（Definition of Done）**
四大平台（Win / macOS Intel / macOS ARM / Linux）从干净机一键装到可用、可配端口、可安全更新且不丢数据、核心能力开箱即用，且测试矩阵全绿、依赖锁定、`server/app.py` 完成路由拆分。

---

## 7. 给下一个对话的实施提示

1. 工作目录 `~/Desktop/my agent`，GitHub `john-lcj/my-agent`（token 见 CONTEXT.md，注意**不要把 token、SMTP 密码、CONTEXT.md 提交进库**）。
2. 改动顺序严格按 Phase 0 → 3；每个 Phase 先在本地跑 `pytest`（`tests/` 有 66 个用例）再推送。
3. 修 P0-1/P0-2 后，务必在**真实 macOS 与 Windows** 上各跑一次干净安装（虚拟机/同事机器），因为这些 bug 都只在“全新机器一键安装”路径暴露，开发机用 `python -m uvicorn` 跑不会触发。
4. 涉及 `.env` 模板、端口、启动器的改动要 Win/macOS/Linux **同步改三处**，否则会再次出现本次的“变量名不一致”问题。
5. P0-4 迁移档案时注意**向后兼容**：老用户的 `persona.yaml` 里如已有 owner 段，首次启动要自动迁到新文件再清空源文件里的个人字段。
