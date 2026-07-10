#requires -Version 5.1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopRoot = Resolve-Path (Join-Path $ScriptDir "..")
$Version = node -e "console.log(require('$DesktopRoot/package.json').version)"

function Write-Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Fail([string]$Message) { Write-Host "ERROR $Message" -ForegroundColor Red; exit 1 }

Write-Info "安装桌面依赖"
npm --prefix $DesktopRoot install
if ($LASTEXITCODE -ne 0) { Write-Fail "npm install 失败" }

Write-Info "准备 App 内置后端与 Python runtime"
$env:CAPTAIN_BUNDLE_TRUST = "installer-bundled"
npm --prefix $DesktopRoot run windows:prepare-bundle
if ($LASTEXITCODE -ne 0) { Write-Fail "windows:prepare-bundle 失败" }

Write-Info "构建 Windows NSIS 安装包"
Push-Location $DesktopRoot
try {
    npx tauri build --bundles nsis
    if ($LASTEXITCODE -ne 0) { Write-Fail "tauri build 失败" }
} finally {
    Pop-Location
}

$BundleDir = Join-Path $DesktopRoot "src-tauri\target\release\bundle\nsis"
$SetupExe = Get-ChildItem -Path $BundleDir -Filter "Captain_${Version}_x64-setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $SetupExe) {
    $SetupExe = Get-ChildItem -Path $BundleDir -Filter "*setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $SetupExe) {
    Write-Fail "未找到 NSIS 安装包, 请检查 $BundleDir"
}

Write-Ok "Windows 安装包已生成: $($SetupExe.FullName)"
Write-Host ""
Write-Host "可直接运行安装包:"
Write-Host "  $($SetupExe.FullName)"
