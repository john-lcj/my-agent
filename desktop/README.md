# Captain Desktop

第一阶段桌面壳:启动本地 Captain 后端,再用原生窗口加载现有 Web UI。

## 开发运行

先检查本机依赖:

```bash
cd desktop
npm install
npm run check
```

macOS:

```bash
cd desktop
npm install
npm run dev
```

Windows PowerShell:

```powershell
cd desktop
npm install
npm run check
npm run dev
```

## 必要依赖

macOS:

- Node.js 18+
- Rust toolchain
- Xcode Command Line Tools
- Python 3.10 到 3.12,优先使用项目根目录 `.venv`

macOS 备用安装命令:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
brew install python@3.12
cd "/Users/luchangjie/Desktop/my agent"
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[all]'
cd desktop
npm run check
```

Windows:

- Node.js 18+
- Rust toolchain
- Microsoft C++ Build Tools
- Microsoft Edge WebView2 Runtime
- Python 3.10 到 3.12,优先使用项目根目录 `.venv\Scripts\python.exe`

Windows PowerShell 依赖安装命令:

```powershell
cd desktop
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows-prereqs.ps1
```

如果是从 GitHub 直接下载安装脚本,请在 PowerShell 中运行:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$u="https://raw.githubusercontent.com/john-lcj/my-agent/main/desktop/scripts/install-windows-prereqs.ps1"; $p=Join-Path $env:TEMP "captain-desktop-prereqs.ps1"; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $p; & $p'
```

安装完成后关闭并重新打开 PowerShell,再执行 `npm run check`。

如果项目不在默认相对路径,可显式指定:

```bash
CAPTAIN_PROJECT_ROOT="/path/to/my agent" npm run dev
```

Windows PowerShell:

```powershell
$env:CAPTAIN_PROJECT_ROOT="C:\path\to\my agent"
npm run dev
```

## 运行机制

- 桌面壳只监听 `127.0.0.1`。
- 端口优先使用 `AGENT_WEB_PORT`,占用时会在 `8000..8099` 自动挑选。
- macOS 打包运行时优先使用 `~/Library/Application Support/Captain/app`。
- Python 优先使用项目或支持目录里的 `.venv`,找不到时再使用系统 Python。
- macOS 桌面模式下模型 Key、授权码、访问 token 优先写入 Keychain,`.env` 只保留非敏感或兼容配置。
- 后端 stdout/stderr 会写入 Application Support 下的 `backend.out.log` / `backend.err.log`。
- 后端启动失败时会打开本地错误页,显示端口、日志位置和排查建议。
- 主窗口关闭时会关闭由桌面壳启动的后端进程。

## macOS 打包路径

当前优先打磨 macOS。推荐的本机装箱流程:

```bash
cd desktop
npm run macos:package
open "$HOME/Applications/Captain.app"
```

这个流程会:

- 把后端源码和 Python 3.12 standalone runtime 打进 `.app`
- 安装 Python 依赖到内置 runtime
- 构建 macOS `.app/.dmg`
- 把 `Captain.app` 复制到 `~/Applications`
- 首次启动时自动解包到 `~/Library/Application Support/Captain/app`
- 首次启动时自动生成独立 `.env`

默认只构建当前机器架构。要同时生成 Apple Silicon 与 Intel 安装包:

```bash
cd desktop
CAPTAIN_MACOS_TARGETS="arm64 x86_64" npm run macos:package
```

生成物形如:

- `desktop/src-tauri/target/release/bundle/dmg/Captain_0.1.0_arm64.dmg`
- `desktop/src-tauri/target/release/bundle/dmg/Captain_0.1.0_x86_64.dmg`

准备 GitHub Release 资料:

```bash
cd desktop
npm run macos:release-assets
```

这个命令会复制两个 DMG 到 `release-assets/v版本号/`,生成 `SHA256SUMS.txt` 和 `RELEASE_NOTES.md`,并打印可执行的 `gh release create ...` 上传命令。

如果只想提前准备后端支持目录:

```bash
cd desktop
npm run macos:install-support
```

## 后续打包

macOS 当前已经采用 App 内置资源 + Application Support 首次启动初始化的方式。系统设置里的「关于」页提供:

- 检查更新:开发/源码版走 git pull;客户版无 git 时打开 GitHub Release/DMG 下载页。
- 打开日志:直接打开当前日志目录。
- 导出诊断包:打包运行摘要、审计/trace 日志和桌面后端启动日志,不会包含模型 Key 明文。

正式客户版后续仍建议补齐 Apple Developer ID 签名、公证、Release 自动发布流水线和首次启动引导。
