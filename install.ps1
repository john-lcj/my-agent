# ============================================================
#  Captain — Windows 一键安装脚本 (PowerShell)
#
#  用法 A（推荐，在 PowerShell 里粘贴运行）：
#    irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
#
#  用法 B（双击运行 .ps1 文件）：
#    右键 install.ps1 → 用 PowerShell 运行
#    窗口执行完毕后按任意键关闭
# ============================================================

# 防止窗口闪退——脚本最后会等待用户按键
$Host.UI.RawUI.WindowTitle = "Captain 安装程序"

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL    = "https://github.com/john-lcj/my-agent.git"
$INSTALL_DIR = "$env:USERPROFILE\captain"
$VENV_DIR    = "$INSTALL_DIR\.venv"
$ENV_FILE    = "$INSTALL_DIR\.env"

# 国内镜像（无需梯子）
$PYTHON_MIRROR = "https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe"
$GIT_MIRROR    = "https://npmmirror.com/mirrors/git-for-windows/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
$PIP_MIRROR    = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"

function Write-Info { param($m) Write-Host "  ▶  $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "  ✓  $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "  ⚠  $m" -ForegroundColor Yellow }
function Write-Err  { param($m)
    Write-Host "`n  ✗  $m" -ForegroundColor Red
    Write-Host "`n按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# ── 下载文件（带进度）─────────────────────────────────────────
function Download-File {
    param($Url, $Dest)
    Write-Info "下载中: $([System.IO.Path]::GetFileName($Dest))"
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($Url, $Dest)
    } catch {
        Write-Err "下载失败: $Url`n$_"
    }
}

# ── 检测 Python ───────────────────────────────────────────────
function Find-Python {
    # 刷新 PATH 后再检测
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    foreach ($cmd in @("python", "python3", "py")) {
        $gc = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $gc) { continue }
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
            if ($ver -match "^(\d+)\.(\d+)") {
                if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 10) {
                    Write-Ok "检测到 Python $ver ($($gc.Source))"
                    return $cmd
                }
            }
        } catch {}
    }
    return $null
}

function Install-Python {
    Write-Warn "未找到 Python 3.10+，使用华为云镜像下载安装（无需梯子）..."
    $installer = "$env:TEMP\python-installer.exe"
    Download-File $PYTHON_MIRROR $installer
    Write-Info "安装 Python（静默安装，约1分钟）..."
    Start-Process -FilePath $installer -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0" -Wait
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    # 刷新 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Ok "Python 安装完成"
}

# ── 检测 Git ──────────────────────────────────────────────────
function Find-Git {
    # 先刷新 PATH，再用 Get-Command 检测（比 try{git} 更可靠）
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    $g = Get-Command git -ErrorAction SilentlyContinue
    if ($g) { Write-Ok "检测到 Git: $($g.Source)"; return $true }
    return $false
}

function Install-Git {
    Write-Warn "未找到 Git，使用 npmmirror 镜像下载（无需梯子）..."
    $installer = "$env:TEMP\git-installer.exe"
    Download-File $GIT_MIRROR $installer
    Write-Info "安装 Git（静默安装，约1分钟）..."
    Start-Process -FilePath $installer -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL" -Wait
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Ok "Git 安装完成"
}

# ── 克隆或更新代码 ────────────────────────────────────────────
function Clone-OrUpdate {
    if (Test-Path "$INSTALL_DIR\.git") {
        Write-Warn "检测到已有安装，执行更新..."
        Push-Location $INSTALL_DIR
        git fetch origin main 2>&1 | Out-Null
        git reset --hard FETCH_HEAD 2>&1 | Out-Null
        Pop-Location
        Write-Ok "代码已更新"
    } else {
        Write-Info "下载 Captain 代码..."
        git clone --depth 1 $REPO_URL $INSTALL_DIR 2>&1
        Write-Ok "代码已下载到 $INSTALL_DIR"
    }
}

# ── 虚拟环境 & 依赖 ──────────────────────────────────────────
function Setup-Venv {
    param($PythonCmd)
    Write-Info "创建 Python 虚拟环境..."
    & $PythonCmd -m venv $VENV_DIR
    $pip = "$VENV_DIR\Scripts\pip.exe"
    Write-Info "安装依赖（使用清华镜像，无需梯子）..."
    & $pip install --quiet --upgrade pip -i $PIP_MIRROR
    if (Test-Path "$INSTALL_DIR\requirements.txt") {
        & $pip install --quiet -r "$INSTALL_DIR\requirements.txt" -i $PIP_MIRROR
    }
    Write-Ok "依赖安装完成"
}

# ── .env 模板 ────────────────────────────────────────────────
function Setup-Env {
    if (Test-Path $ENV_FILE) { Write-Warn ".env 已存在，跳过"; return }
    Write-Info "生成 .env 配置模板..."
    @"
# ============================================================
#  Captain 配置文件 — 请填写 API Key 后保存
# ============================================================

# DeepSeek（推荐，国内直连）
DEEPSEEK_API_KEY=sk-xxx

# OpenAI（可选）
# OPENAI_API_KEY=sk-xxx

AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek/deepseek-chat

# Pro 授权码（留空以 Free 版运行）
CAPTAIN_LICENSE_KEY=

AGENT_PORT=8000
AGENT_API_TOKEN=change-me-to-random-string
"@ | Set-Content $ENV_FILE -Encoding UTF8
    Write-Ok ".env 已生成: $ENV_FILE"
}

# ── 启动脚本 ──────────────────────────────────────────────────
function Create-Launcher {
    $launcher = "$INSTALL_DIR\captain.bat"
    @"
@echo off
title Captain AI Agent
cd /d "$INSTALL_DIR"
call "$VENV_DIR\Scripts\activate.bat"
echo Captain 启动中...
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
pause
"@ | Set-Content $launcher -Encoding UTF8
    Write-Ok "启动脚本已创建: $launcher"
}

# ── 完成提示 ──────────────────────────────────────────────────
function Print-Done {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║      Captain 安装完成！              ║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  第 1 步：" -ForegroundColor White -NoNewline
    Write-Host "用记事本打开 $ENV_FILE"
    Write-Host "           填入 DEEPSEEK_API_KEY（DeepSeek 注册：platform.deepseek.com）"
    Write-Host ""
    Write-Host "  第 2 步：" -ForegroundColor White -NoNewline
    Write-Host "双击运行 $INSTALL_DIR\captain.bat"
    Write-Host ""
    Write-Host "  第 3 步：" -ForegroundColor White -NoNewline
    Write-Host "浏览器打开 http://localhost:8000"
    Write-Host ""
    Write-Host "  购买 Pro：" -ForegroundColor Cyan -NoNewline
    Write-Host "https://irestart-your-life.club/#pricing"
    Write-Host ""
}

# ══════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  ⚡ Captain 安装程序 (Windows)" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# Git
if (-not (Find-Git)) { Install-Git }
if (-not (Find-Git)) { Write-Err "Git 安装失败，请手动下载: https://npmmirror.com/mirrors/git-for-windows/v2.45.2.windows.1/Git-2.45.2-64-bit.exe" }

# Python
$pythonCmd = Find-Python
if (-not $pythonCmd) { Install-Python; $pythonCmd = Find-Python }
if (-not $pythonCmd) { Write-Err "Python 安装失败，请手动下载: https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe" }

Clone-OrUpdate

Push-Location $INSTALL_DIR
Setup-Venv -PythonCmd $pythonCmd
Setup-Env
Create-Launcher
Pop-Location

Print-Done

Write-Host "  按任意键关闭此窗口..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
