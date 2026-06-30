# Captain 实施清单（可勾选）

> 配套文档：`DIAGNOSIS_AND_PLAN.md`（每条的根因/修复方案/验收标准看那里）
> 用法：执行对话照 Phase 0 → 3 顺序逐条勾选；每个 Phase 合并前先跑 `pytest`（tests/ 有 66 用例）。
> 编号与诊断文档一一对应（P0-1、P1-3…）。

---

## Phase 0 — 紧急热修（当天，1 个 PR）
> 决定“新装用户能不能用、会不会丢数据”，最先合并。

### P0-1 macOS/Linux 启动器起不来服务
- [x] `server/app.py` 末尾追加 `if __name__ == "__main__": run()`
- [x] `install.sh` 的 `create_launcher` 改为 `exec python -m uvicorn server.app:app --host 127.0.0.1 --port "${AGENT_WEB_PORT:-8000}"`
- [x] launchd plist 的 `ProgramArguments` 同步改成 `-m uvicorn ...`
- [ ] 验收：干净 macOS 跑 `bash install.sh` → `bash ~/captain/captain.sh`，`curl localhost:<port>/healthz` 返回 200

### P0-2 端口三套配置打架
- [x] 统一变量为 `AGENT_WEB_PORT`（默认 8000）
- [x] `.env` 模板：写 `AGENT_WEB_PORT=8000`，删除 `AGENT_PORT`
- [x] `install.sh`：launcher、print_done 提示、launchd/systemd 全部用 `${AGENT_WEB_PORT:-8000}`
- [x] `install.ps1`：captain.bat 用 `--port %AGENT_WEB_PORT%`，VBS healthz/打开 URL 用同一端口
- [ ] 验收：改 `.env` 为 9000，重启后服务监听 9000 且图标打开的也是 9000

### P0-4 更新 `git reset --hard` 清空用户个人档案
- [x] owner 档案从 `persona.yaml` 迁到非跟踪文件（`data/owner.json` 或 `~/.captain/owner.json`）
- [x] `core/persona.load_persona` 改为合并：源码 `persona.yaml`(仅 agent 段) + 用户档案文件(owner 段)
- [x] `/api/profile` 读写指向新文件，`persona.yaml` 只保留 `agent:` 段
- [x] 向后兼容：首启检测老 `persona.yaml` 的 owner 段 → 自动迁移到新文件再清空源文件个人字段
- [x] 更新流程加兜底：reset 前 `git stash`，reset 后 `stash pop`（冲突保留用户版）
- [ ] 验收：填档案 → 触发更新 → 档案仍在；`data/owner.json` 不随 git 变化

- [ ] **Phase 0 合并前：`pytest` 全绿 + 真实 macOS/Windows 各跑一次干净安装**

---

## Phase 1 — 更新链路与 Windows 修复（1-2 个 PR）

### P0-3 一键更新后自动重启
- [x] 更新端点改为「先 spawn 分离进程再退出」：Unix 用 `subprocess.Popen([...], start_new_session=True)`
- [x] 启动器自带 supervisor：Windows captain.bat 加 `:loop … goto loop`；launchd 改 `KeepAlive=true`；systemd 改 `Restart=always`
- [x] 前端更新成功后轮询 `/healthz` 自动重连（提示“正在重启，约5秒后刷新”）
- [ ] 验收：点检查更新（确有新 commit），10 秒内服务自动可用、前端自动重连

### P1-1 Windows 路径被冒号切碎
- [x] `config.py:87` `.split(":")` → `.split(os.pathsep)`
- [x] `skills/paths.py:25` `extra.split(":")` → `extra.split(os.pathsep)`
- [ ] 验收：Windows 设 `AGENT_PERSONAL_DIRS=C:\a;D:\b` 解析为两条完整路径

### P1-3 更新走国内镜像 + 校验失败
- [x] `server/app.py` 更新端点 pip 命令加 `-i <镜像>`（复用安装时镜像/读 `PIP_INDEX_URL`）
- [x] 检查 pip returncode，失败回传前端明确错误
- [ ] 验收：仅留镜像也能更新成功；镜像失败时前端显示错误

### P1-4 依赖拆分 + Playwright 内核
- [x] 拆 `requirements-base.txt`（fastapi/uvicorn/websockets/openai/PyYAML 最小集）+ 可选组（browser/office/memory）
- [x] 安装脚本默认只装 base；重依赖运行时懒加载并给清晰提示
- [x] browser 组安装末尾可选执行 `python -m playwright install chromium`（带询问/超时兜底）
- [ ] 验收：默认安装 2 分钟内完成；不装 browser 时核心聊天/文件/搜索可用

### P1-5 依赖锁定 + Python 区间
- [x] 在跑通环境 `pip freeze > requirements.lock.txt` 并随仓库分发
- [x] 安装/更新优先用 lock
- [x] 声明支持 Python 区间（建议 3.10–3.12），在该区间冒烟测试
- [ ] 验收：两台机器按 lock 装得到一致版本；3.11 与 3.12 各跑通

- [ ] **Phase 1 合并前：`pytest` 全绿 + 四平台冒烟**

---

## Phase 2 — 安全加固（1 个 PR）

### P2-1 防 DNS rebinding / CSRF
- [x] 校验 `Host` 头必须是 localhost/127.0.0.1[:port]，否则拒绝
- [x] 写/执行类端点校验 `Origin`/`Sec-Fetch-Site: same-origin`，或 loopback 也要 `X-Agent-Token`
- [x] 显式加 CORS 策略（默认禁跨域）
- [x] 验收：`Origin: http://evil.com` 的 POST `/api/...` 被拒；正常前端不受影响

### P2-2 随机 AUTH_SECRET
- [x] 安装时生成随机 `AUTH_SECRET` 写入 `.env`
- [x] 远程模式（非 loopback/经代理）检测到默认值则拒绝并提示
- [x] 验收：新装机 `.env` 含随机 secret；默认值下开远程被拒

### P1-2 persona 隐私收尾
- [x] 确认 `persona.yaml` 不再含个人数据（随 P0-4 完成）
- [ ] 如历史提交含隐私，按需 `git filter-repo` 清史
- [x] 验收：`git ls-files | grep persona` 仅含 agent 人设

- [x] **Phase 2 合并前：`pytest` 全绿**

---

## Phase 3 — 可维护性与打磨（持续）

### P2-4 拆分巨型 app.py
- [x] 把 channels/tasks/system/profile/license 端点迁到 `server/routers/`
- [x] `create_app()` 内仅做依赖装配
- [x] 验收：`server/app.py` < 800 行，测试全绿

### P3 打磨项
- [x] P3-1 `install.sh:55` 限定 `MAJ==3 且 10<=MIN<=12`
- [x] P3-2 统一 DeepSeek 默认模型（核对 `llm/model_registry` 实际 id）
- [x] P3-3 统一三平台 `.env` 模板（同字段/同变量名/同默认端口）
- [x] P3-4 macOS 软链用 `$(brew --prefix)/bin` 而非写死 `/usr/local/bin`
- [x] P3-5 VBS 改为轮询 `/healthz` 再打开浏览器（替代固定 Sleep 3500）
- [x] P3-6 install.ps1 开头设 `[Console]::OutputEncoding=UTF8` 或改纯 ASCII
- [x] P3-7 附带 `requirements.lock.txt`（随 P1-5）

### CI
- [ ] 接入 CI 自动跑测试矩阵（四平台 + Python 3.11/3.12）

---

## 跨平台验收矩阵（“完全体”全绿才算完成）

| 场景 | Win10/11 | macOS Intel | macOS ARM | Linux apt |
|------|---|---|---|---|
| 干净机一键安装 | ☐ | ☐ | ☐ | ☐ |
| 启动器拉起服务并打开浏览器 | ☐ | ☐ | ☐ | ☐ |
| 端口可由 `.env` 配置且一致 | ☐ | ☐ | ☐ | ☐ |
| 填档案 → 重启后仍在 | ☐ | ☐ | ☐ | ☐ |
| 检查更新 → 自动重启回到可用 | ☐ | ☐ | ☐ | ☐ |
| 更新后档案不丢 | ☐ | ☐ | ☐ | ☐ |
| `AGENT_PERSONAL_DIRS` 多路径生效 | ☐ | ☐ | ☐ | ☐ |
| 核心聊天/文件/搜索（不含 browser）可用 | ☐ | ☐ | ☐ | ☐ |
| browser.* 装 chromium 后可用 | ☐ | ☐ | ☐ | ☐ |
| 恶意 Origin 的 /api 请求被拒 | ☐ | ☐ | ☐ | ☐ |

---

## Definition of Done（完全体）
四平台从干净机一键装到可用、可配端口、可安全更新且不丢数据、核心能力开箱即用；测试矩阵全绿；依赖锁定；`server/app.py` 完成路由拆分。
