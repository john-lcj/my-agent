#requires -Version 5.1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopRoot = Resolve-Path (Join-Path $ScriptDir "..")
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$ResourceApp = Join-Path $DesktopRoot "src-tauri\resources\app"
$CacheRoot = if ($env:CAPTAIN_WINDOWS_CACHE_DIR) { $env:CAPTAIN_WINDOWS_CACHE_DIR } else { Join-Path $env:LOCALAPPDATA "Captain\cache" }
$PyRuntime = Join-Path $ResourceApp "runtime\python"
$PyExe = Join-Path $PyRuntime "python.exe"

function Write-Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "OK  $Message" -ForegroundColor Green }
function Write-Fail([string]$Message) { Write-Host "ERROR $Message" -ForegroundColor Red; exit 1 }

function Get-ProjectVersion {
    $pyproject = Join-Path $RepoRoot "pyproject.toml"
    $match = Select-String -Path $pyproject -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return "0.1.0"
}

function Sync-BackendSource {
    Write-Info "准备 App 内置后端资源"
    if (Test-Path $ResourceApp) {
        Remove-Item -Recurse -Force $ResourceApp
    }
    New-Item -ItemType Directory -Force -Path $ResourceApp | Out-Null

    $excludeDirs = @(
        ".git", ".github", ".cursor", ".pytest_cache", ".venv", ".venv312",
        "__pycache__", "build", "data", "demo", "desktop", "evals", "htmlcov",
        "license_server", "logs", "release-assets", "report", "tests", "uploads",
        "收件箱", "产物"
    )
    $excludeFiles = @(
        ".DS_Store", ".dockerignore", ".env", "Dockerfile", "Makefile",
        "CLAUDE.local.md", "docker-compose.yml", "*.pyc", "*.pem", "*.github_token",
        "票据市场行情报告_*.md"
    )

    $robocopyArgs = @(
        $RepoRoot, $ResourceApp, "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS"
    )
    foreach ($dir in $excludeDirs) {
        $robocopyArgs += "/XD"
        $robocopyArgs += $dir
    }
    foreach ($file in $excludeFiles) {
        $robocopyArgs += "/XF"
        $robocopyArgs += $file
    }

    & robocopy @robocopyArgs | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        Write-Fail "robocopy 同步失败, exit code $code"
    }

    $version = Get-ProjectVersion
    $builtAt = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
    $stampLines = @(
        "version=$version",
        "built_at=$builtAt"
    )
    Push-Location $RepoRoot
    try {
        $gitHead = (& git rev-parse --short HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and $gitHead) {
            $stampLines += "git=$gitHead"
        }
    } finally {
        Pop-Location
    }
    Set-Content -Path (Join-Path $ResourceApp ".captain_bundle_stamp") -Value $stampLines -Encoding UTF8
}

function Download-PythonRuntime {
    Write-Info "解析 Python standalone runtime (x86_64-pc-windows-msvc)"
    $cachePython = Join-Path $CacheRoot "python"
    New-Item -ItemType Directory -Force -Path $cachePython | Out-Null
    $metaPath = Join-Path $cachePython "python-build-standalone-latest.json"

    $resolveScript = @'
import json
import os
import re
import sys
import urllib.request

meta_path, cache_dir = sys.argv[1], sys.argv[2]
pattern = re.compile(r"^cpython-3\.12\.\d+\+\d+-x86_64-pc-windows-msvc-install_only\.tar\.gz$")

matches = []
try:
    url = "https://api.github.com/repos/indygreg/python-build-standalone/releases/latest"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    matches = [
        {"name": asset["name"], "url": asset["browser_download_url"]}
        for asset in data.get("assets", [])
        if pattern.match(asset.get("name", ""))
    ]
except Exception as exc:
    print(f"[prepare-windows-bundle] GitHub latest lookup failed, trying local cache: {exc}", file=sys.stderr)
    if os.path.isdir(cache_dir):
        cached = sorted(name for name in os.listdir(cache_dir) if pattern.match(name))
        if cached:
            matches = [{"name": cached[-1], "url": ""}]

if not matches:
    raise SystemExit("No matching python-build-standalone asset for x86_64-pc-windows-msvc")

with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(matches[0], f)
'@

    $bootstrapPy = Join-Path $cachePython "_resolve_runtime.py"
    Set-Content -Path $bootstrapPy -Value $resolveScript -Encoding UTF8
    $pyCmd = $null
    foreach ($candidate in @("python", "py")) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        if ($candidate -eq "py") {
            & py -3.12 $bootstrapPy $metaPath $cachePython
        } else {
            & python $bootstrapPy $metaPath $cachePython
        }
        if ($LASTEXITCODE -eq 0) { $pyCmd = $candidate; break }
    }
    if (-not $pyCmd) {
        Write-Fail "需要 Python 3.12 来解析 runtime 下载地址"
    }

    $meta = Get-Content $metaPath -Raw | ConvertFrom-Json
    $asset = [string]$meta.name
    $url = [string]$meta.url
    $tarball = Join-Path $cachePython $asset

    if (-not (Test-Path $tarball)) {
        if (-not $url) {
            Write-Fail "缺少 Python runtime 缓存且无法联网解析下载地址: $asset"
        }
        Write-Info "下载 Python runtime: $asset"
        Invoke-WebRequest -Uri $url -OutFile $tarball -UseBasicParsing
    } else {
        Write-Ok "Python runtime 缓存已存在"
    }

    $runtimeDir = Join-Path $ResourceApp "runtime"
    if (Test-Path $PyRuntime) {
        Remove-Item -Recurse -Force $PyRuntime
    }
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Write-Info "解压 Python runtime"
    & tar -xzf $tarball -C $runtimeDir
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Python runtime 解压失败"
    }
    if (-not (Test-Path $PyExe)) {
        Write-Fail "Python runtime 解压失败: $PyExe 不存在"
    }
}

function Install-PythonDependencies {
    Write-Info "安装 Python 依赖到内置 runtime"
    & $PyExe -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { Write-Fail "ensurepip 失败" }
    & $PyExe -m pip install -U pip
    if ($LASTEXITCODE -ne 0) { Write-Fail "pip upgrade 失败" }

    $installTarget = "${ResourceApp}[all]"
    & $PyExe -m pip install --no-warn-script-location $installTarget
    if ($LASTEXITCODE -ne 0) { Write-Fail "pip install 失败" }

    & $PyExe -c "import fastapi, uvicorn, server.app; print('embedded backend import ok')"
    if ($LASTEXITCODE -ne 0) { Write-Fail "embedded backend import 校验失败" }

    $sitePackages = Join-Path $PyRuntime "Lib\site-packages"
    if (Test-Path $sitePackages) {
        Get-ChildItem -Path $sitePackages -Recurse -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("tests", "test", "__pycache__") } |
            ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
    }
    Get-ChildItem -Path $ResourceApp -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
    $buildDir = Join-Path $ResourceApp "build"
    if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
    Get-ChildItem -Path $ResourceApp -Filter "*.egg-info" -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }

    Write-Ok "内置 Python runtime 已就绪"
}

Sync-BackendSource
Download-PythonRuntime
Install-PythonDependencies

Write-Ok "App 内置资源已准备好: $ResourceApp"
