# ============================================================
#  Captain — Windows 一键安装脚本 (PowerShell)
#  Portable 方案：内置 Python + Git，无需任何预装环境
#
#  运行方式（在 PowerShell 粘贴一行）：
#    irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
# ============================================================

$Host.UI.RawUI.WindowTitle = "Captain 安装程序"
$ErrorActionPreference = "Stop"

# ── 路径 ──────────────────────────────────────────────────────
$INSTALL_DIR = "$env:USERPROFILE\captain"
$RUNTIME_DIR = "$INSTALL_DIR\runtime"
$PYTHON_DIR  = "$RUNTIME_DIR\python"
$GIT_DIR     = "$RUNTIME_DIR\git"
$PYTHON_EXE  = "$PYTHON_DIR\python.exe"
$GIT_EXE     = "$GIT_DIR\bin\git.exe"
$REPO_URL    = "https://github.com/john-lcj/my-agent.git"

# ── 国内镜像（全部无需梯子）──────────────────────────────────
$PYTHON_ZIP  = "https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip"
$GIT_SFX     = "https://npmmirror.com/mirrors/git-for-windows/v2.45.2.windows.1/PortableGit-2.45.2-64-bit.7z.exe"
$GETPIP_URL  = "https://bootstrap.pypa.io/get-pip.py"
$PIP_MIRROR  = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"

# ── 工具函数 ──────────────────────────────────────────────────
function Write-Info { param($m) Write-Host "  ▶  $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "  ✓  $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "  ⚠  $m" -ForegroundColor Yellow }
function Pause-Exit { param($code=0)
    Write-Host "`n  按任意键关闭..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit $code
}
function Write-Err { param($m)
    Write-Host "`n  ✗  $m" -ForegroundColor Red
    Pause-Exit 1
}

function Download-File {
    param($Url, $Dest)
    $name = [System.IO.Path]::GetFileName($Dest)
    Write-Info "下载 $name ..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($Url, $Dest)
    } catch {
        Write-Err "下载失败: $Url`n$_"
    }
}

# ── 1. Portable Python ────────────────────────────────────────
function Setup-Python {
    if (Test-Path $PYTHON_EXE) { Write-Ok "Python 已就绪 (portable)"; return }
    New-Item -ItemType Directory -Force -Path $PYTHON_DIR | Out-Null
    $zip = "$env:TEMP\python-embed.zip"
    Download-File $PYTHON_ZIP $zip
    Write-Info "解压 Python ..."
    Expand-Archive -Path $zip -DestinationPath $PYTHON_DIR -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    # 开启 site-packages（embeddable 默认关闭，pip 需要它）
    $pth = Get-ChildItem "$PYTHON_DIR\*._pth" | Select-Object -First 1
    if ($pth) {
        (Get-Content $pth.FullName) -replace '#import site','import site' |
            Set-Content $pth.FullName
    }

    # 安装 pip
    Write-Info "安装 pip ..."
    $getpip = "$env:TEMP\get-pip.py"
    Download-File $GETPIP_URL $getpip
    & $PYTHON_EXE $getpip --quiet -i $PIP_MIRROR
    Remove-Item $getpip -Force -ErrorAction SilentlyContinue
    Write-Ok "Python + pip 就绪"
}

# ── 2. Portable Git ───────────────────────────────────────────
function Setup-Git {
    if (Test-Path $GIT_EXE) { Write-Ok "Git 已就绪 (portable)"; return }
    New-Item -ItemType Directory -Force -Path $GIT_DIR | Out-Null
    $sfx = "$env:TEMP\PortableGit.exe"
    Download-File $GIT_SFX $sfx
    Write-Info "解压 Git ..."
    # PortableGit 是 7z 自解压包，-o 指定输出目录，-y 自动确认
    Start-Process -FilePath $sfx -ArgumentList "-o`"$GIT_DIR`"", "-y" -Wait -NoNewWindow
    Remove-Item $sfx -Force -ErrorAction SilentlyContinue
    Write-Ok "Git 就绪"
}

# ── 3. 克隆 / 更新代码 ────────────────────────────────────────
function Clone-OrUpdate {
    if (Test-Path "$INSTALL_DIR\.git") {
        # 已是 git repo，直接更新
        Write-Warn "已有安装，执行更新..."
        & $GIT_EXE -C $INSTALL_DIR fetch origin main 2>&1 | Out-Null
        & $GIT_EXE -C $INSTALL_DIR reset --hard FETCH_HEAD 2>&1 | Out-Null
        Write-Ok "代码已更新"
    } else {
        # 目录可能已存在（runtime 子目录），用 init+fetch+reset 代替 clone
        Write-Info "下载 Captain 代码 ..."
        & $GIT_EXE -C $INSTALL_DIR init 2>&1 | Out-Null
        & $GIT_EXE -C $INSTALL_DIR remote add origin $REPO_URL 2>&1 | Out-Null
        & $GIT_EXE -C $INSTALL_DIR fetch --depth 1 origin main 2>&1
        & $GIT_EXE -C $INSTALL_DIR reset --hard FETCH_HEAD 2>&1 | Out-Null
        Write-Ok "代码已下载"
    }
}

# ── 4. 安装 Python 依赖 ───────────────────────────────────────
function Install-Deps {
    $pip = "$PYTHON_DIR\Scripts\pip.exe"
    if (-not (Test-Path $pip)) { $pip = "$PYTHON_DIR\pip.exe" }
    Write-Info "安装依赖（清华镜像）..."
    if (Test-Path "$INSTALL_DIR\requirements.txt") {
        & $PYTHON_EXE -m pip install --quiet -r "$INSTALL_DIR\requirements.txt" -i $PIP_MIRROR
    }
    Write-Ok "依赖安装完成"
}

# ── 5. 生成 .env 模板 ─────────────────────────────────────────
function Setup-Env {
    $env_file = "$INSTALL_DIR\.env"
    if (Test-Path $env_file) { Write-Warn ".env 已存在，跳过"; return }
    @"
# ============================================================
#  Captain 配置文件 — 填写 API Key 后保存
# ============================================================

# DeepSeek（推荐，国内直连）https://platform.deepseek.com
DEEPSEEK_API_KEY=sk-xxx

# OpenAI（可选）
# OPENAI_API_KEY=sk-xxx

AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek/deepseek-chat

# Pro 授权码（留空以 Free 版运行）
CAPTAIN_LICENSE_KEY=

AGENT_PORT=8000
AGENT_API_TOKEN=change-me-to-random-string
"@ | Set-Content $env_file -Encoding UTF8
    Write-Ok ".env 已生成: $env_file"
}

# ── 6. 启动脚本 captain.bat ───────────────────────────────────
function Create-Launcher {
    $bat = "$INSTALL_DIR\captain.bat"
    @"
@echo off
title Captain AI Agent
cd /d "%~dp0"
set PATH=%~dp0runtime\python;%~dp0runtime\python\Scripts;%~dp0runtime\git\bin;%PATH%
echo Captain 启动中... 请稍候
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
pause
"@ | Set-Content $bat -Encoding UTF8
    Write-Ok "启动脚本: $bat"
}

# ── 完成提示 ──────────────────────────────────────────────────
function Print-Done {
    Write-Host ""
    Write-Host "  ╔════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║       Captain 安装完成！               ║" -ForegroundColor Green
    Write-Host "  ╚════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  第 1 步  " -NoNewline -ForegroundColor White
    Write-Host "用记事本打开并填写 API Key："
    Write-Host "           $INSTALL_DIR\.env"
    Write-Host ""
    Write-Host "  第 2 步  " -NoNewline -ForegroundColor White
    Write-Host "双击启动："
    Write-Host "           $INSTALL_DIR\captain.bat"
    Write-Host ""
    Write-Host "  第 3 步  " -NoNewline -ForegroundColor White
    Write-Host "浏览器打开 http://localhost:8000"
    Write-Host ""
    Write-Host "  购买 Pro  https://irestart-your-life.club/#pricing" -ForegroundColor Cyan
    Write-Host ""
}

# ══════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  ⚡ Captain 安装程序 (Windows · Portable)" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

Setup-Python
Setup-Git
Clone-OrUpdate
Install-Deps
Setup-Env
Create-Launcher
Print-Done

Pause-Exit 0
