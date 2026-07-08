#requires -Version 5.1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopRoot = Resolve-Path (Join-Path $ScriptDir "..")
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Version = node -e "console.log(require('$DesktopRoot/package.json').version)"
$Tag = if ($env:CAPTAIN_RELEASE_TAG) { $env:CAPTAIN_RELEASE_TAG } else { "v$Version" }
$BundleDir = if ($env:CAPTAIN_WINDOWS_BUNDLE_DIR) {
    $env:CAPTAIN_WINDOWS_BUNDLE_DIR
} else {
    Join-Path $DesktopRoot "src-tauri\target\release\bundle\nsis"
}
$OutDir = if ($env:CAPTAIN_RELEASE_OUT_DIR) {
    $env:CAPTAIN_RELEASE_OUT_DIR
} else {
    Join-Path $RepoRoot "release-assets\$Tag"
}
$NotesOut = Join-Path $OutDir "RELEASE_NOTES.txt"

function Write-Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Fail([string]$Message) { Write-Host "ERROR $Message" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$SetupExe = Get-ChildItem -Path $BundleDir -Filter "Captain_${Version}_x64-setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $SetupExe) {
    $SetupExe = Get-ChildItem -Path $BundleDir -Filter "*setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $SetupExe) {
    Write-Fail "缺少 Windows 安装包。请先运行 npm run windows:package"
}

Write-Info "复制 setup.exe 到 release-assets/$Tag"
Copy-Item -Force $SetupExe.FullName (Join-Path $OutDir $SetupExe.Name)

Write-Info "生成 SHA256SUMS.txt"
$hash = (Get-FileHash -Path (Join-Path $OutDir $SetupExe.Name) -Algorithm SHA256).Hash.ToLower()
$shaPath = Join-Path $OutDir "SHA256SUMS.txt"
Set-Content -Path $shaPath -Value ("{0}  {1}" -f $hash, $SetupExe.Name) -Encoding UTF8

Write-Info "生成发布说明草稿"
@"
Captain $Version

Downloads

- Windows x64: $($SetupExe.Name)
- Checksums: SHA256SUMS.txt

Install

1. Download setup.exe.
2. If SmartScreen warns about an unknown publisher, choose More info, then Run anyway.
3. On first launch, follow the setup guide to configure the app token and model keys.

Update

- In the app, open Settings -> Diagnostics -> Check for updates.
- Reinstalling keeps .env, data, and logs under `%LOCALAPPDATA%\Captain\app`.
"@ | Set-Content -Path $NotesOut -Encoding UTF8

Write-Ok "Release 资料已准备好: $OutDir"
Write-Host ""
Write-Host "下一步上传 GitHub Release:"
Write-Host "  gh release upload `"$Tag`" `"$OutDir\$($SetupExe.Name)`" `"$OutDir\SHA256SUMS.txt`" --clobber"
