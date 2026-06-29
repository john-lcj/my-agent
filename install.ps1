# ============================================================
#  Captain — Windows 一键安装脚本 (PowerShell · Portable)
#
#  在 PowerShell 粘贴运行：
#    irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
# ============================================================

$Host.UI.RawUI.WindowTitle = "Captain 安装程序"
# 不用 Stop——外部命令写 stderr 不应被当成致命错误
$ErrorActionPreference = "Continue"

$INSTALL_DIR = "$env:USERPROFILE\captain"
$PYTHON_DIR  = "$INSTALL_DIR\runtime\python"
$GIT_DIR     = "$INSTALL_DIR\runtime\git"
$PYTHON_EXE  = "$PYTHON_DIR\python.exe"
$GIT_EXE     = "$GIT_DIR\bin\git.exe"
$REPO_URL    = "https://github.com/john-lcj/my-agent.git"

$PYTHON_ZIP  = "https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip"
$GIT_SFX     = "https://npmmirror.com/mirrors/git-for-windows/v2.45.2.windows.1/PortableGit-2.45.2-64-bit.7z.exe"
$GETPIP_URL  = "https://bootstrap.pypa.io/get-pip.py"
$PIP_MIRROR  = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"

function Write-Info { param($m) Write-Host "  ▶  $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "  ✓  $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "  ⚠  $m" -ForegroundColor Yellow }

function Pause-Exit {
    param([int]$code = 0)
    Write-Host "`n  按任意键关闭..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit $code
}

function Write-Err {
    param($m)
    Write-Host "`n  ✗  $m" -ForegroundColor Red
    Pause-Exit 1
}

# 下载文件，失败则报错退出
function Download-File {
    param([string]$Url, [string]$Dest)
    $name = [System.IO.Path]::GetFileName($Dest)
    Write-Info "下载 $name ..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($Url, $Dest)
    }
    catch {
        Write-Err "下载失败: $Url`n  $_"
    }
}

# 静默运行外部命令，stdout+stderr 全部丢弃
# 用 $LASTEXITCODE 判断是否成功
function Run-Silent {
    param([string]$Exe, [string[]]$Args)
    & $Exe @Args 2>&1 | Out-Null
}

# ── 1. Portable Python ────────────────────────────────────────
function Setup-Python {
    if (Test-Path $PYTHON_EXE) {
        Write-Ok "Python 已就绪 (portable)"
        return
    }
    New-Item -ItemType Directory -Force -Path $PYTHON_DIR | Out-Null

    $zip = "$env:TEMP\captain-python.zip"
    Download-File $PYTHON_ZIP $zip
    Write-Info "解压 Python ..."
    Expand-Archive -Path $zip -DestinationPath $PYTHON_DIR -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    # 开启 site-packages（embeddable 默认注释掉 import site）
    $pth = Get-ChildItem "$PYTHON_DIR\*._pth" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pth) {
        $content = Get-Content $pth.FullName -Raw
        $content = $content -replace '#\s*import site', 'import site'
        Set-Content -Path $pth.FullName -Value $content -NoNewline
    }

    # 安装 pip（警告 PATH 不在系统 PATH 无需理会，脚本直接用绝对路径）
    $getpip = "$env:TEMP\get-pip.py"
    Download-File $GETPIP_URL $getpip
    Write-Info "安装 pip ..."
    & $PYTHON_EXE $getpip --quiet --no-warn-script-location -i $PIP_MIRROR 2>&1 | Out-Null
    Remove-Item $getpip -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $PYTHON_EXE)) { Write-Err "Python 安装失败" }
    Write-Ok "Python + pip 就绪"
}

# ── 2. Portable Git ───────────────────────────────────────────
function Setup-Git {
    if (Test-Path $GIT_EXE) {
        Write-Ok "Git 已就绪 (portable)"
        return
    }
    New-Item -ItemType Directory -Force -Path $GIT_DIR | Out-Null

    $sfx = "$env:TEMP\captain-git.exe"
    Download-File $GIT_SFX $sfx
    Write-Info "解压 Git ..."
    # PortableGit 是 7z 自解压包
    & $sfx "-o$GIT_DIR" "-y" 2>&1 | Out-Null
    Remove-Item $sfx -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $GIT_EXE)) { Write-Err "Git 安装失败" }
    Write-Ok "Git 就绪"
}

# ── 3. 拉取代码（init+fetch+reset，兼容非空目录）────────────
function Clone-OrUpdate {
    if (Test-Path "$INSTALL_DIR\.git") {
        Write-Warn "检测到已有安装，执行更新..."
        Run-Silent $GIT_EXE @("-C", $INSTALL_DIR, "fetch", "--depth=1", "origin", "main")
        Run-Silent $GIT_EXE @("-C", $INSTALL_DIR, "reset", "--hard", "FETCH_HEAD")
        Write-Ok "代码已更新"
    }
    else {
        Write-Info "下载 Captain 代码（首次约需1分钟）..."
        # init -b main 避免 git 输出默认分支名称 hint
        Run-Silent $GIT_EXE @("-C", $INSTALL_DIR, "init", "-b", "main")
        Run-Silent $GIT_EXE @("-C", $INSTALL_DIR, "remote", "add", "origin", $REPO_URL)
        # fetch 显示进度（让用户知道在工作）
        & $GIT_EXE -C $INSTALL_DIR fetch --depth=1 origin main 2>&1 |
            Where-Object { $_ -notmatch '^hint:' } |
            ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
        Run-Silent $GIT_EXE @("-C", $INSTALL_DIR, "reset", "--hard", "FETCH_HEAD")
        if (-not (Test-Path "$INSTALL_DIR\server")) { Write-Err "代码下载失败，请检查网络" }
        Write-Ok "代码已下载"
    }
}

# ── 4. Python 依赖 ────────────────────────────────────────────
function Install-Deps {
    $req = "$INSTALL_DIR\requirements.txt"
    if (-not (Test-Path $req)) { return }
    Write-Info "安装 Python 依赖（清华镜像）..."
    & $PYTHON_EXE -m pip install --quiet --no-warn-script-location `
        -r $req -i $PIP_MIRROR 2>&1 | Out-Null
    Write-Ok "依赖安装完成"
}

# ── 5. .env 模板 ──────────────────────────────────────────────
function Setup-Env {
    $f = "$INSTALL_DIR\.env"
    if (Test-Path $f) { Write-Warn ".env 已存在，跳过"; return }
    $envContent = @"
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
"@
    [System.IO.File]::WriteAllText($f, $envContent, [System.Text.UTF8Encoding]::new($false))
    Write-Ok ".env 已生成"
}

# ── 6. 启动脚本 captain.bat ───────────────────────────────────
function Create-Launcher {
    $bat = "$INSTALL_DIR\captain.bat"
    # 用 ASCII 写入，避免 BOM 导致 cmd.exe 乱码
    $batContent = "@echo off`r`ntitle Captain AI Agent`r`ncd /d `"%~dp0`"`r`nset PATH=%~dp0runtime\python;%~dp0runtime\python\Scripts;%~dp0runtime\git\bin;%PATH%`r`necho Captain 启动中... 请稍候`r`npython -m uvicorn server.app:app --host 127.0.0.1 --port 8000`r`npause`r`n"
    [System.IO.File]::WriteAllText($bat, $batContent, [System.Text.Encoding]::ASCII)
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
    Write-Host "填写 API Key：$INSTALL_DIR\.env"
    Write-Host "  第 2 步  " -NoNewline -ForegroundColor White
    Write-Host "双击启动：$INSTALL_DIR\captain.bat"
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

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

Setup-Python
Setup-Git
Clone-OrUpdate
Install-Deps
Setup-Env
Create-Launcher
Print-Done

Pause-Exit 0
