# ============================================================
#  Captain — Windows 一键安装脚本 (PowerShell)
#  用法（以管理员身份运行 PowerShell）：
#    irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
# ============================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL   = "https://github.com/john-lcj/my-agent.git"
$INSTALL_DIR = "$env:USERPROFILE\captain"
$VENV_DIR   = "$INSTALL_DIR\.venv"
$ENV_FILE   = "$INSTALL_DIR\.env"
$MIN_PYTHON = "3.10"

function Write-Info  { param($m) Write-Host "▶  $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "✓  $m" -ForegroundColor Green }
function Write-Warn  { param($m) Write-Host "⚠  $m" -ForegroundColor Yellow }
function Write-Err   { param($m) Write-Host "✗  $m" -ForegroundColor Red; exit 1 }

# ── 检测 Python ───────────────────────────────────────────────
function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -match "^(\d+)\.(\d+)") {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                if ($maj -ge 3 -and $min -ge 10) {
                    Write-Info "检测到 Python $ver ($cmd)"
                    return $cmd
                }
            }
        } catch {}
    }
    return $null
}

function Install-Python {
    Write-Warn "未找到 Python 3.10+，尝试通过 winget 安装..."
    try {
        winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
        Write-Ok "Python 安装完成，请关闭并重新打开 PowerShell 后再次运行此脚本"
        exit 0
    } catch {
        Write-Err "自动安装失败，请手动下载：https://www.python.org/downloads/"
    }
}

# ── 检测 Git ──────────────────────────────────────────────────
function Find-Git {
    try {
        $v = git --version 2>$null
        if ($v) { return $true }
    } catch {}
    return $false
}

function Install-Git {
    Write-Warn "未找到 git，尝试通过 winget 安装..."
    try {
        winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
        Write-Ok "Git 安装完成，请关闭并重新打开 PowerShell 后再次运行此脚本"
        exit 0
    } catch {
        Write-Err "自动安装失败，请手动下载：https://git-scm.com/download/win"
    }
}

# ── 下载或更新代码 ────────────────────────────────────────────
function Clone-OrUpdate {
    if (Test-Path "$INSTALL_DIR\.git") {
        Write-Warn "检测到已有安装，执行更新..."
        Push-Location $INSTALL_DIR
        git fetch origin main
        git reset --hard FETCH_HEAD
        Pop-Location
    } else {
        Write-Info "正在下载 Captain..."
        git clone --depth 1 $REPO_URL $INSTALL_DIR
        Write-Ok "代码已下载到 $INSTALL_DIR"
    }
}

# ── 创建虚拟环境 & 安装依赖 ───────────────────────────────────
function Setup-Venv {
    param($PythonCmd)
    Write-Info "创建 Python 虚拟环境..."
    & $PythonCmd -m venv $VENV_DIR
    $pip = "$VENV_DIR\Scripts\pip.exe"
    Write-Info "安装依赖（首次可能需要 1-3 分钟）..."
    & $pip install --quiet --upgrade pip
    if (Test-Path "$INSTALL_DIR\requirements.txt") {
        & $pip install --quiet -r "$INSTALL_DIR\requirements.txt"
    }
    Write-Ok "依赖安装完成"
}

# ── 生成 .env 模板 ────────────────────────────────────────────
function Setup-Env {
    if (Test-Path $ENV_FILE) {
        Write-Warn ".env 已存在，跳过"
        return
    }
    Write-Info "生成 .env 配置模板..."
    @"
# ============================================================
#  Captain 配置文件  —  请填写以下内容后保存
# ============================================================

# DeepSeek（推荐）
DEEPSEEK_API_KEY=sk-xxx

# OpenAI（可选）
# OPENAI_API_KEY=sk-xxx

# 默认模型
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek/deepseek-chat

# Pro 授权码（留空则以 Free 版运行）
CAPTAIN_LICENSE_KEY=

# 服务端口
AGENT_PORT=8765

# WebSocket 令牌
AGENT_API_TOKEN=change-me-to-random-string
"@ | Set-Content $ENV_FILE -Encoding UTF8
    Write-Ok ".env 已生成：$ENV_FILE"
}

# ── 创建启动脚本 ──────────────────────────────────────────────
function Create-Launcher {
    $launcher = "$INSTALL_DIR\captain.bat"
    @"
@echo off
cd /d "$INSTALL_DIR"
call "$VENV_DIR\Scripts\activate.bat"
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
"@ | Set-Content $launcher -Encoding UTF8
    Write-Ok "已创建启动脚本：$launcher"
}

# ── 打印完成信息 ──────────────────────────────────────────────
function Print-Done {
    Write-Host ""
    Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║        Captain 安装完成 🎉             ║" -ForegroundColor Green
    Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  第 1 步：填写 API Key" -ForegroundColor White
    Write-Host "    用记事本打开：$ENV_FILE"
    Write-Host "    填入 DEEPSEEK_API_KEY"
    Write-Host ""
    Write-Host "  第 2 步：启动 Captain" -ForegroundColor White
    Write-Host "    双击运行：$INSTALL_DIR\captain.bat"
    Write-Host "    浏览器打开 http://localhost:8000"
    Write-Host ""
    Write-Host "  第 3 步（可选）：激活 Pro" -ForegroundColor White
    Write-Host "    购买 Pro：https://irestart-your-life.club/#pricing" -ForegroundColor Cyan
    Write-Host ""
}

# ── 主流程 ────────────────────────────────────────────────────
Write-Host ""
Write-Host "⚡ Captain 安装程序 (Windows)" -ForegroundColor Cyan
Write-Host ""

# 检测 Git
if (-not (Find-Git)) { Install-Git }

# 检测 Python
$pythonCmd = Find-Python
if (-not $pythonCmd) { Install-Python; $pythonCmd = Find-Python }
if (-not $pythonCmd) { Write-Err "未找到可用的 Python 3.10+，请手动安装后重试" }

Clone-OrUpdate
Push-Location $INSTALL_DIR
Setup-Venv -PythonCmd $pythonCmd
Setup-Env
Create-Launcher
Pop-Location
Print-Done
