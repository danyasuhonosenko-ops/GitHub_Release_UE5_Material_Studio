<# :
@echo off
chcp 65001 >nul
title AI PBR Studio for 3ds Max - GitHub Installer & Updater
set "BAT_FILE=%~f0"
set "SRC_DIR=%~dp0"
set "TARGET_ENU=%~1"
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_EXE%" set "PS_EXE=powershell"
"%PS_EXE%" -NoProfile -Sta -ExecutionPolicy Bypass -Command "Invoke-Expression ([System.IO.File]::ReadAllText($env:BAT_FILE, [System.Text.Encoding]::UTF8))"
echo.
pause
exit /b
#>

Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host '  Corona ComfyPBR Studio & UE5 Exporter for 3ds Max (GitHub + OTA Edition)' -ForegroundColor White
Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host ''

try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$src = ($env:SRC_DIR).TrimEnd('\')
$target = $env:TARGET_ENU
$ghMaxBase = 'https://raw.githubusercontent.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/main/3dsMax'
$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

$maxRoot = Join-Path $env:LOCALAPPDATA 'Autodesk\3dsMax'
$candidates = @()
if (Test-Path $maxRoot) {
    $candidates = @(Get-ChildItem -Path $maxRoot -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'ENU') } | Sort-Object Name -Descending)
}

if (-not $target) {
    if ($candidates.Count -eq 1) {
        $target = Join-Path $candidates[0].FullName 'ENU'
        Write-Host ('[Auto-detected] ' + $target) -ForegroundColor Green
    } elseif ($candidates.Count -gt 1) {
        Write-Host 'Detected Autodesk 3ds Max ENU folders:' -ForegroundColor Yellow
        for ($i = 0; $i -lt $candidates.Count; $i++) {
            Write-Host ('  [' + ($i + 1) + '] ' + (Join-Path $candidates[$i].FullName 'ENU')) -ForegroundColor White
        }
        $pick = Read-Host 'Select number [1]'
        $idx = 0
        if ($pick -match '^\d+$') { $idx = [Math]::Max(0, [Math]::Min($candidates.Count - 1, ([int]$pick - 1))) }
        $target = Join-Path $candidates[$idx].FullName 'ENU'
    } else {
        $typed = Read-Host 'Enter full path to 3ds Max ENU folder (e.g. %LOCALAPPDATA%\Autodesk\3dsMax\2024 - 64bit\ENU)'
        if ($typed) { $target = $typed.Trim('"').Trim() }
    }
}

if (-not $target) { Write-Host '[Cancelled]' -ForegroundColor Red; exit 1 }

$pyDst = Join-Path $target 'scripts\AIPBRMaterialStudio'
$startupDst = Join-Path $target 'scripts\startup'
$iconsDst = Join-Path $target 'UI_ln\Icons'
New-Item -ItemType Directory -Force -Path $pyDst, $startupDst, $iconsDst | Out-Null

$coreFiles = @('studio_qt_theme.py','pbr_credits_ledger.py','comfy_to_corona.py','presets_data.py','corona_pbr_studio_qt.py','corona_ue5_exporter_qt.py','run_job.py','Corona_ComfyPBR_Studio.ms','Corona_to_UE5_Exporter.ms','AIPBR_Max_Macros_Startup.ms','Corona_plagin.json','Corona_plagin_chord.json')
foreach ($fn in $coreFiles) {
    $dstFile = Join-Path $pyDst $fn
    $localSrc = Join-Path $src $fn
    $ok = $false
    try {
        Invoke-WebRequest -Uri ($ghMaxBase + '/' + $fn + '?t=' + $ts) -OutFile $dstFile -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        $ok = $true
    } catch {}
    if (-not $ok -and (Test-Path $localSrc)) {
        Copy-Item $localSrc $dstFile -Force
    }
}
foreach ($sub in @('Avatars','icons')) {
    $sd = Join-Path $src $sub
    if (Test-Path $sd) {
        $dd = Join-Path $pyDst $sub
        New-Item -ItemType Directory -Force -Path $dd | Out-Null
        Copy-Item (Join-Path $sd '*') $dd -Force
    }
}
foreach ($st in @('Corona_ComfyPBR_Studio.ms','AIPBR_Max_Macros_Startup.ms')) {
    $fromDst = Join-Path $pyDst $st
    $fromSrc = Join-Path $src $st
    if (Test-Path $fromDst) { Copy-Item $fromDst (Join-Path $startupDst $st) -Force }
    elseif (Test-Path $fromSrc) { Copy-Item $fromSrc (Join-Path $startupDst $st) -Force }
}
$icoSrc = Join-Path $pyDst 'icons'
if (Test-Path $icoSrc) { Copy-Item (Join-Path $icoSrc 'ComfyPBRStudio_*.png') $iconsDst -Force -ErrorAction SilentlyContinue }

Write-Host ''
Write-Host '[DONE] Installed GitHub + OTA Edition into:' -ForegroundColor Green
Write-Host ('  Scripts : ' + $pyDst) -ForegroundColor White
Write-Host ('  Startup : ' + $startupDst) -ForegroundColor White
Write-Host 'Restart 3ds Max, then Customize -> Customize User Interface -> Category: AI ArchViz.' -ForegroundColor Cyan
