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
- Python 优先使用项目 `.venv`,找不到时再使用系统 Python。
- 主窗口关闭时会关闭由桌面壳启动的后端进程。

## 后续打包

第一阶段不内置 Python 运行时。正式面向客户的安装包需要把 Python、依赖、后端、前端一起装箱,并接入自动更新。
