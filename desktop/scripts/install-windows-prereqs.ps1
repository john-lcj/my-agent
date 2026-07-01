#requires -Version 5.1
param(
    [switch]$SkipProjectVenv
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "OK  $Message" -ForegroundColor Green
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "WARN $Message" -ForegroundColor Yellow
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Add-KnownPath {
    $paths = @(
        "$env:ProgramFiles\nodejs",
        "$env:USERPROFILE\.cargo\bin",
        "$env:LOCALAPPDATA\Programs\Python\Python312",
        "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts",
        "$env:ProgramFiles\Python312",
        "$env:ProgramFiles\Python312\Scripts"
    )
    foreach ($p in $paths) {
        if ((Test-Path $p) -and ($env:Path -notlike "*$p*")) {
            $env:Path = "$p;$env:Path"
        }
    }
}

function Install-WingetPackage {
    param(
        [string]$Id,
        [string]$Name,
        [string]$Override = ""
    )

    if (-not (Test-Command "winget")) {
        throw "winget was not found. Please install App Installer from Microsoft Store, then rerun this script."
    }

    Write-Step "Installing $Name"
    & winget list --exact --id $Id --accept-source-agreements | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$Name already installed"
        Add-KnownPath
        return
    }

    $args = @(
        "install",
        "--exact",
        "--id", $Id,
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent"
    )
    if ($Override.Trim()) {
        $args += @("--override", $Override)
    }

    & winget @args
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed for $Name ($Id), exit code $LASTEXITCODE"
    }
    Add-KnownPath
}

function Find-Python312 {
    Add-KnownPath
    if (Test-Command "py") {
        & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3.12") }
    }
    if (Test-Command "python") {
        & python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return @("python") }
    }
    return @()
}

function Invoke-Python312 {
    param([string[]]$Arguments)
    $cmd = Find-Python312
    if ($cmd.Count -eq 0) {
        throw "Python 3.12 was not found after installation."
    }
    $exe = $cmd[0]
    $prefix = @()
    if ($cmd.Count -gt 1) { $prefix = $cmd[1..($cmd.Count - 1)] }
    $allArgs = @($prefix) + @($Arguments)
    & $exe @allArgs
}

function Resolve-ProjectRoot {
    $candidate = Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction SilentlyContinue
    if ($candidate -and (Test-Path (Join-Path $candidate.Path "server\app.py"))) {
        return $candidate.Path
    }
    return ""
}

Write-Host ""
Write-Host "Captain Desktop Windows prerequisites" -ForegroundColor Cyan
Write-Host "This script installs Node.js, Python 3.12, Rust, WebView2, and C++ Build Tools." -ForegroundColor DarkGray

if (-not (Test-Elevated)) {
    Write-WarnLine "If Visual Studio Build Tools asks for elevation, accept the Windows prompt."
}

Install-WingetPackage -Id "OpenJS.NodeJS.LTS" -Name "Node.js LTS"
Install-WingetPackage -Id "Python.Python.3.12" -Name "Python 3.12"
Install-WingetPackage -Id "Rustlang.Rustup" -Name "Rustup"
Install-WingetPackage -Id "Microsoft.EdgeWebView2Runtime" -Name "Microsoft Edge WebView2 Runtime"
Install-WingetPackage `
    -Id "Microsoft.VisualStudio.2022.BuildTools" `
    -Name "Microsoft C++ Build Tools" `
    -Override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

Add-KnownPath

$root = Resolve-ProjectRoot
if ($SkipProjectVenv -or -not $root) {
    Write-WarnLine "Project root not found from this script location, skipping .venv setup."
} else {
    Write-Step "Setting up Captain Python environment"
    Push-Location $root
    try {
        Invoke-Python312 -Arguments @("-m", "venv", ".venv")
        & ".\.venv\Scripts\python.exe" -m pip install -U pip
        & ".\.venv\Scripts\python.exe" -m pip install -e ".[all]"
    } finally {
        Pop-Location
    }
}

Write-Ok "Prerequisites installed. Close and reopen PowerShell, then run: cd desktop; npm install; npm run check; npm run dev"
