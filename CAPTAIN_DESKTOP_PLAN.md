# Captain Desktop 第一阶段方案

目标:把 Captain 做成接近 Codex 使用形态的桌面协作应用,但保持现有 Web/后端架构不重写。第一阶段先交付一个跨平台桌面壳,负责启动本地 Captain 服务并加载现有前端。

## 第一阶段边界

- 支持 macOS 优先交付路径,Windows 暂保留开发运行路径。
- 桌面壳启动时自动选择本机端口,设置 `AGENT_WEB_HOST=127.0.0.1` 和 `AGENT_WEB_PORT`。
- 桌面壳复用 `server.app:run`,不复制后端启动逻辑。
- 桌面窗口加载 `http://127.0.0.1:<port>/`,继续使用现有 Chat/Cowork/设置/治理能力。
- 关闭桌面主窗口时,同步关闭由桌面壳拉起的后端进程。
- macOS 打包时把后端源码、前端资源、Python 3.12 standalone runtime 和依赖打进 `.app`。
- macOS 首次启动时自动解包到 `~/Library/Application Support/Captain/app`,并生成本机 `.env`。

## 为什么先用 Tauri

- macOS/Windows 原生窗口能力成熟,安装包体积比 Electron 更轻。
- 可用 Rust 侧管理本地进程、端口、窗口和后续托盘/自动更新。
- 前端仍是现有 `frontend/index.html + app.js + styles.css`,不需要立刻迁移到 React/Vite。

## macOS / Windows 兼容策略

- Python 解析顺序:
  - Windows:优先 `.venv/Scripts/python.exe`,再找打包运行目录下的 `runtime/python/python.exe`,最后用系统 `python`。
  - macOS/Linux:优先 `.venv/bin/python`,再找 `runtime/python/bin/python3`,最后用系统 `python3` 或 `python`。
- 项目根解析顺序:
  - `CAPTAIN_PROJECT_ROOT`
  - `AGENT_PROJECT_ROOT`
  - macOS 的 `~/Library/Application Support/Captain/app`
  - macOS `.app` 内的 `Contents/Resources/app`
  - 开发模式下的 `desktop/src-tauri/../..`
  - 当前工作目录
- 端口解析:
  - 优先 `AGENT_WEB_PORT`
  - 不可用时在 `8000..8099` 内自动选择空闲端口
- 桌面模式下默认只绑定 `127.0.0.1`,避免意外对外暴露。

## 后续阶段

1. macOS 安装包:已具备 `.app` 内置后端、Application Support 首次初始化、DMG 拖拽安装路径;后续补签名、公证和首次启动引导。
2. 自动更新:源码/开发版走 git 更新;客户版无 git 时打开 GitHub Release/DMG 下载页。后续可接 Tauri updater 做应用内增量更新。
3. 托盘与后台驻留:关闭窗口不一定退出,可从托盘重新打开。
4. 系统能力:文件拖拽、目录授权、通知、登录启动、协议唤起。
5. 本地安全:桌面环境下自动生成 `AUTH_SECRET`,限制 `AGENT_WORKSPACE_ROOT`;macOS App 中模型 Key、授权码、访问 token 优先迁移到 Keychain。
6. 崩溃与诊断:已提供后端启动失败错误页、端口占用自动换端口、打开日志、导出诊断包;后续可接崩溃上报或用户授权上传。
7. 双架构:打包脚本支持 `CAPTAIN_MACOS_TARGETS="arm64 x86_64"` 同时构建 Apple Silicon 与 Intel DMG。

## 验收清单

- `npm install` 后在 `desktop/` 执行 `npm run dev` 可以打开 Captain 桌面窗口。
- 关闭窗口后,由桌面壳启动的后端进程会退出。
- macOS 和 Windows 都不要求用户手工输入 uvicorn 命令。
- 服务仅监听 `127.0.0.1`。
- 现有浏览器版本仍可通过 `python -m server.app` 或安装脚本启动。
- macOS 客户版可从「关于」页打开日志、导出诊断包、检查更新。
