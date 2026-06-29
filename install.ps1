# ============================================================
#  Captain — Windows 一键安装脚本 (PowerShell · Portable)
#
#  在 PowerShell 粘贴运行：
#    irm https://raw.githubusercontent.com/john-lcj/my-agent/main/install.ps1 | iex
# ============================================================

$Host.UI.RawUI.WindowTitle = "Captain 安装程序"
$ErrorActionPreference = "Continue"
# 强制控制台 UTF-8 输出，避免中文/制表符在旧 cp936 终端乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

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

function Download-File {
    param([string]$Url, [string]$Dest)
    Write-Info "下载 $([System.IO.Path]::GetFileName($Dest)) ..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($Url, $Dest)
    } catch {
        Write-Err "下载失败: $Url`n  $_"
    }
}

# ── 1. Portable Python ────────────────────────────────────────
function Setup-Python {
    if (Test-Path $PYTHON_EXE) { Write-Ok "Python 已就绪"; return }

    New-Item -ItemType Directory -Force -Path $PYTHON_DIR | Out-Null
    $zip = "$env:TEMP\captain-python.zip"
    Download-File $PYTHON_ZIP $zip
    Write-Info "解压 Python ..."
    Expand-Archive -Path $zip -DestinationPath $PYTHON_DIR -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    # 修复 _pth 文件：逐行处理，确保 import site 和 Lib\site-packages 都启用
    $pth = Get-ChildItem "$PYTHON_DIR\*._pth" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pth) { Write-Err "找不到 Python _pth 文件" }

    $lines = [System.IO.File]::ReadAllLines($pth.FullName)
    $newLines = [System.Collections.Generic.List[string]]::new()
    $hasSite = $false
    $hasSitePackages = $false

    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '#import site' -or $trimmed -eq '# import site') {
            $newLines.Add('import site')
            $hasSite = $true
        } elseif ($trimmed -eq 'import site') {
            $newLines.Add($line)
            $hasSite = $true
        } elseif ($trimmed -eq 'Lib\site-packages') {
            $newLines.Add($line)
            $hasSitePackages = $true
        } else {
            $newLines.Add($line)
        }
    }
    if (-not $hasSite)         { $newLines.Add('import site') }
    if (-not $hasSitePackages) { $newLines.Add('Lib\site-packages') }

    [System.IO.File]::WriteAllLines($pth.FullName, $newLines, [System.Text.Encoding]::ASCII)

    # 创建 site-packages 目录（pip 需要它存在）
    New-Item -ItemType Directory -Force -Path "$PYTHON_DIR\Lib\site-packages" | Out-Null

    # 安装 pip
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
    if (Test-Path $GIT_EXE) { Write-Ok "Git 已就绪"; return }

    New-Item -ItemType Directory -Force -Path $GIT_DIR | Out-Null
    $sfx = "$env:TEMP\captain-git.exe"
    Download-File $GIT_SFX $sfx
    Write-Info "解压 Git ..."
    & $sfx "-o$GIT_DIR" "-y" 2>&1 | Out-Null
    Remove-Item $sfx -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $GIT_EXE)) { Write-Err "Git 安装失败" }
    Write-Ok "Git 就绪"
}

# ── 3. 拉取代码 ───────────────────────────────────────────────
function Clone-OrUpdate {
    if (Test-Path "$INSTALL_DIR\.git") {
        Write-Warn "已有安装，执行更新..."
        & $GIT_EXE -C $INSTALL_DIR fetch --depth=1 origin main 2>&1 | Out-Null
        & $GIT_EXE -C $INSTALL_DIR reset --hard FETCH_HEAD 2>&1 | Out-Null
        Write-Ok "代码已更新"
    } else {
        Write-Info "下载 Captain 代码..."
        & $GIT_EXE -C $INSTALL_DIR init -b main 2>&1 | Out-Null
        & $GIT_EXE -C $INSTALL_DIR remote add origin $REPO_URL 2>&1 | Out-Null
        Write-Info "正在拉取，请稍候（约1分钟）..."
        & $GIT_EXE -C $INSTALL_DIR fetch --depth=1 origin main 2>&1 | Out-Null
        & $GIT_EXE -C $INSTALL_DIR reset --hard FETCH_HEAD 2>&1 | Out-Null
        if (-not (Test-Path "$INSTALL_DIR\server")) { Write-Err "代码下载失败，请检查网络" }
        Write-Ok "代码已下载"
    }
}

# ── 4. 安装依赖 ───────────────────────────────────────────────
function Install-Deps {
    $req = "$INSTALL_DIR\requirements.txt"
    if (-not (Test-Path $req)) { Write-Warn "未找到 requirements.txt，跳过"; return }
    Write-Info "安装 Python 依赖（清华镜像，首次约需3分钟）..."
    & $PYTHON_EXE -m pip install --quiet --no-warn-script-location `
        -r $req -i $PIP_MIRROR 2>&1 | Out-Null
    # 验证核心依赖
    $check = & $PYTHON_EXE -c "import uvicorn; import fastapi" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Err "依赖安装失败: $check" }
    Write-Ok "依赖安装完成"
}

# ── 5. .env 模板 ──────────────────────────────────────────────
function Setup-Env {
    $f = "$INSTALL_DIR\.env"
    if (Test-Path $f) { Write-Warn ".env 已存在，跳过"; return }
    # 生成随机 token
    $randToken = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    $content = @(
        "# Captain 配置文件 - 填写 API Key 后保存",
        "",
        "# DeepSeek（推荐，国内直连）https://platform.deepseek.com",
        "DEEPSEEK_API_KEY=sk-xxx",
        "",
        "# OpenAI（可选）",
        "# OPENAI_API_KEY=sk-xxx",
        "",
        "# Anthropic Claude（可选）",
        "# ANTHROPIC_API_KEY=sk-ant-xxx",
        "",
        "AGENT_PROVIDER=deepseek",
        "AGENT_MODEL=deepseek/deepseek-chat",
        "",
        "# Pro 授权码（留空以 Free 版运行）",
        "CAPTAIN_LICENSE_KEY=",
        "",
        "AGENT_WEB_PORT=8000",
        "# 安装时自动生成的随机令牌，无需修改",
        "AGENT_API_TOKEN=$randToken"
    )
    [System.IO.File]::WriteAllLines($f, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Ok ".env 已生成: $f"
}

# ── 6. 启动脚本 captain.bat ───────────────────────────────────
function Create-Launcher {
    $bat = "$INSTALL_DIR\captain.bat"
    $lines = @(
        "@echo off",
        "title Captain AI Agent",
        "cd /d ""%~dp0""",
        "set PATH=%~dp0runtime\python;%~dp0runtime\python\Scripts;%~dp0runtime\git\bin;%PATH%",
        ":: 从 .env 读取 AGENT_WEB_PORT（默认 8000）",
        "set AGENT_WEB_PORT=8000",
        "if exist ""%~dp0.env"" (",
        "  for /f ""usebackq tokens=1,* delims=="" %%a in (""%~dp0.env"") do (",
        "    if /i ""%%a""==""AGENT_WEB_PORT"" set AGENT_WEB_PORT=%%b",
        "  )",
        ")",
        ":loop",
        "echo Captain 启动中 ^(端口 %AGENT_WEB_PORT%^)...",
        "python.exe -m uvicorn server.app:app --host 127.0.0.1 --port %AGENT_WEB_PORT%",
        "echo Captain 已停止，5秒后自动重启...",
        "timeout /t 5 /nobreak >nul",
        "goto loop"
    )
    [System.IO.File]::WriteAllLines($bat, $lines, [System.Text.Encoding]::ASCII)
    Write-Ok "启动脚本: $bat"
}

# ── 7. 桌面快捷方式 ──────────────────────────────────────────
function Create-Shortcut {
    $bat = "$INSTALL_DIR\captain.bat"

    # VBS 启动器：若服务未运行则先启动，然后打开浏览器
    # 用 here-string 生成，避免中文字符 + 引号拼接问题
    $vbs = "$INSTALL_DIR\captain_launch.vbs"
    $vbsContent = @"
Set WShell = CreateObject("WScript.Shell")
bRunning = False
On Error Resume Next
Set oHTTP = CreateObject("MSXML2.XMLHTTP")
oHTTP.Open "GET", "http://localhost:8000/healthz", False
oHTTP.Send
If oHTTP.Status = 200 Then bRunning = True
On Error GoTo 0
If Not bRunning Then
    WShell.Run """$bat""", 1, False
    Dim waited
    waited = 0
    Do While waited < 30000
        WScript.Sleep 1000
        waited = waited + 1000
        On Error Resume Next
        Set oHTTP2 = CreateObject("MSXML2.XMLHTTP")
        oHTTP2.Open "GET", "http://localhost:8000/healthz", False
        oHTTP2.Send
        If oHTTP2.Status = 200 Then
            waited = 30000
        End If
        On Error GoTo 0
    Loop
End If
WShell.Run "http://localhost:8000"
"@
    # ASCII 写入（VBS 不需要 Unicode）
    [System.IO.File]::WriteAllText($vbs, $vbsContent, [System.Text.Encoding]::ASCII)

    # 桌面快捷方式
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnkPath = "$desktop\Captain.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($lnkPath)
    $lnk.TargetPath      = "wscript.exe"
    $lnk.Arguments       = """$vbs"""
    $lnk.WorkingDirectory = $INSTALL_DIR
    $lnk.Description     = "Captain AI Agent — 启动并打开浏览器"
    # 使用 Shell32 里的星形图标（外观醒目）
    $lnk.IconLocation    = "%SystemRoot%\system32\shell32.dll,43"
    $lnk.Save()
    Write-Ok "桌面快捷方式已创建: $lnkPath"
}

# ── 完成提示 ──────────────────────────────────────────────────
function Print-Done {
    Write-Host ""
    Write-Host "  ╔════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║       Captain 安装完成！               ║" -ForegroundColor Green
    Write-Host "  ╚════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  第 1 步  " -NoNewline -ForegroundColor White
    Write-Host "填写 API Key："
    Write-Host "           $INSTALL_DIR\.env"
    Write-Host ""
    Write-Host "  第 2 步  " -NoNewline -ForegroundColor White
    Write-Host "双击桌面上的 Captain 图标启动"
    Write-Host ""
    Write-Host "  第 3 步  " -NoNewline -ForegroundColor White
    Write-Host "浏览器会自动打开 http://localhost:8000"
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

Setup-Python    # 1. 解压 Python，修复 _pth，装 pip
Setup-Git       # 2. 解压 PortableGit
Clone-OrUpdate  # 3. 拉取应用代码
Install-Deps    # 4. pip install requirements.txt → site-packages
Setup-Env       # 5. 生成 .env 模板
Create-Launcher # 6. 生成 captain.bat
Create-Shortcut # 7. 桌面快捷方式

Print-Done
Pause-Exit 0
