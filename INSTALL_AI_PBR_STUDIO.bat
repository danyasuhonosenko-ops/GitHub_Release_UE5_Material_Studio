<# :
@echo off
chcp 65001 >nul
title AI PBR Studio - One-Click UE5 Installer and Auto-Updater
set "BAT_FILE=%~f0"
set "SRC_DIR=%~dp0"
set "TARGET_DIR=%~1"
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_EXE%" set "PS_EXE=powershell"
"%PS_EXE%" -NoProfile -Sta -ExecutionPolicy Bypass -Command "Invoke-Expression ([System.IO.File]::ReadAllText($env:BAT_FILE, [System.Text.Encoding]::UTF8))"
echo.
pause
exit /b
#>

Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host '  AI PBR & Substance Studio for Unreal Engine 5 (5.4 - 5.8)' -ForegroundColor White
Write-Host '  Automated Client Installer & Online Version Updater' -ForegroundColor Gray
Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host ''

$ErrorActionPreference = 'Continue'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}
$src = $env:SRC_DIR
if (-not $src -or -not (Test-Path $src)) {
    $src = [System.IO.Path]::GetTempPath()
}
$target = $env:TARGET_DIR
$ghBase = 'https://raw.githubusercontent.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/main'
$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$latestVer = 'v2.0.6'
$otaHash = ''
$activeUrl = 'https://desktop-kbo2jj9.tail754f20.ts.net'

Write-Host '[1/3] Проверка и скачивание свежей версии плагина с GitHub / Сервера...' -ForegroundColor Cyan
try {
    $cfgRaw = Invoke-WebRequest -Uri ($ghBase + '/render_cluster_config.json?t=' + $ts) -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
    $cfgJson = $cfgRaw.Content | ConvertFrom-Json
    if ($cfgJson.latest_version) { $latestVer = [string]$cfgJson.latest_version }
    if ($cfgJson.ota_hash) { $otaHash = [string]$cfgJson.ota_hash }
    if ($cfgJson.active_comfy_url) { $activeUrl = [string]$cfgJson.active_comfy_url }
    foreach ($f in @('comfy_to_ue.py','comfy_to_corona.py','presets_data.py','UE_plagin.json','init_unreal.py','render_cluster_config.json')) {
        try {
            Invoke-WebRequest -Uri ($ghBase + '/' + $f + '?t=' + $ts) -OutFile (Join-Path $src $f) -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
        } catch {}
    }
    Write-Host ('[OK] Скачана актуальная сборка: ' + $latestVer + ' (OTA: ' + $otaHash + ')') -ForegroundColor Green
} catch {
    Write-Host '[!] Не удалось связаться с GitHub, используется локальный пакет.' -ForegroundColor Yellow
}

if (-not $target -or -not (Test-Path $target)) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $top = New-Object System.Windows.Forms.Form
        $top.TopMost = $true
        $top.StartPosition = 'CenterScreen'
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = 'Выберите корневую папку вашего проекта Unreal Engine 5 (где находится файл .uproject)'
        $dlg.ShowNewFolderButton = $false
        if ($dlg.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) {
            $target = $dlg.SelectedPath
        }
    } catch {}
}

if (-not $target -or -not (Test-Path $target)) {
    Write-Host ''
    Write-Host 'Введите или вставьте полный путь к папке вашего проекта Unreal Engine 5' -ForegroundColor Yellow
    Write-Host '(например: D:\UnrealProjects\MyProject) и нажмите Enter:' -ForegroundColor Gray
    $typedPath = Read-Host 'Путь к проекту'
    if ($typedPath) {
        $target = $typedPath.Trim('"').Trim()
    }
}

if (-not $target -or -not (Test-Path $target)) {
    Write-Host '[Отменено: папка проекта не выбрана или не существует]' -ForegroundColor Red
    exit 1
}

if (Test-Path $target -PathType Leaf) {
    $target = Split-Path $target -Parent
}

$uproj = Get-ChildItem -Path $target -Filter '*.uproject' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $uproj) {
    Write-Host '[!] В выбранной папке не найден файл .uproject, но установка/обновление в Content/ будет выполнено.' -ForegroundColor Yellow
}

Write-Host '[2/3] Обновление файлов плагина в проекте UE5...' -ForegroundColor Cyan
$contentDir = Join-Path $target 'Content'
$widgetDir = Join-Path $contentDir 'AIPBR_Studio_Plugin'
$legacyWidgetDir = Join-Path $contentDir 'ConfyUI_plagin'
$pyDir = Join-Path $contentDir 'Python'
New-Item -ItemType Directory -Force -Path $widgetDir | Out-Null
New-Item -ItemType Directory -Force -Path $pyDir | Out-Null

$uassetDst = Join-Path $widgetDir 'BP_ComfyPanel.uasset'
$uassetSrc = Join-Path $src 'Content\AIPBR_Studio_Plugin\BP_ComfyPanel.uasset'
if (Test-Path $uassetSrc) {
    Copy-Item $uassetSrc $uassetDst -Force
} else {
    try {
        Write-Host '  -> Скачивание BP_ComfyPanel.uasset с GitHub (архив был запущен без распаковки)...' -ForegroundColor Gray
        Invoke-WebRequest -Uri ($ghBase + '/Content/AIPBR_Studio_Plugin/BP_ComfyPanel.uasset?t=' + $ts) -OutFile $uassetDst -UseBasicParsing -TimeoutSec 25 -ErrorAction Stop
    } catch {
        Write-Host '  [!] Не удалось скачать BP_ComfyPanel.uasset. Распакуйте ZIP-архив перед запуском батника!' -ForegroundColor Red
    }
}

# Remove legacy ConfyUI_plagin widget folder after migrating to AIPBR_Studio_Plugin
if (Test-Path $uassetDst) {
    $legacyAsset = Join-Path $legacyWidgetDir 'BP_ComfyPanel.uasset'
    if (Test-Path $legacyAsset) {
        Remove-Item $legacyAsset -Force -ErrorAction SilentlyContinue
    }
    if ((Test-Path $legacyWidgetDir) -and @(Get-ChildItem -Path $legacyWidgetDir -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item $legacyWidgetDir -Force -ErrorAction SilentlyContinue
    }
}

foreach ($f in @('comfy_to_ue.py','comfy_to_corona.py','presets_data.py','UE_plagin.json','init_unreal.py')) {
    $p = Join-Path $src $f
    $dstPy = Join-Path $pyDir $f
    if (Test-Path $p) {
        Copy-Item $p $dstPy -Force
    } else {
        try {
            Invoke-WebRequest -Uri ($ghBase + '/' + $f + '?t=' + $ts) -OutFile $dstPy -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
        } catch {}
    }
}

if ($uproj) {
    try {
        $j = Get-Content $uproj.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $j.Plugins) { $j | Add-Member -NotePropertyName 'Plugins' -NotePropertyValue @() }
        foreach ($reqPlug in @('PythonScriptPlugin','EditorScriptingUtilities')) {
            $found = $j.Plugins | Where-Object { $_.Name -eq $reqPlug }
            if (-not $found) {
                $j.Plugins += [PSCustomObject]@{ Name = $reqPlug; Enabled = $true }
            } else {
                $found.Enabled = $true
            }
        }
        $j | ConvertTo-Json -Depth 10 | Set-Content $uproj.FullName -Encoding UTF8
        Write-Host ('[OK] Плагины PythonScriptPlugin и EditorScriptingUtilities активированы в ' + $uproj.Name) -ForegroundColor Green
    } catch {}
}

Write-Host '[3/3] Синхронизация версии и баланса с сервером лицензий...' -ForegroundColor Cyan
$licFile = Join-Path $pyDir 'studio_license_state.json'
if (Test-Path $licFile) {
    try {
        $st = Get-Content $licFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $st | Add-Member -NotePropertyName 'comfy_url' -NotePropertyValue $activeUrl -Force
        $bodyObj = @{
            instance_id = [string]$st.instance_id
            studio_version = $latestVer
            comfy_url = $activeUrl
            credits_remaining = [int]$st.credits
            total_spent = [int]$st.total_spent
            redeemed_keys = @($st.redeemed_keys)
            ota_hash = $otaHash
            event = 'bat_updated'
        } | ConvertTo-Json -Compress
        $audResp = Invoke-RestMethod -Uri ($activeUrl + '/api/audit') -Method Post -ContentType 'application/json' -Body $bodyObj -TimeoutSec 6
        if ($audResp.action -eq 'clamp_to_legitimate' -and $null -ne $audResp.set_credits) {
            $st.credits = [int]$audResp.set_credits
        }
        $st | ConvertTo-Json -Depth 6 | Set-Content $licFile -Encoding UTF8
        Write-Host ('[OK] Copy ID ' + $st.instance_id + ' синхронизирован (Версия: ' + $latestVer + ', Баланс: ' + $st.credits + ' Gens)') -ForegroundColor Green
    } catch {}
}

Write-Host ''
Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host ('[ГОТОВО] AI PBR & Substance Studio ' + $latestVer + ' успешно установлен / обновлён!') -ForegroundColor Green
Write-Host ('  -> Проект: ' + $target) -ForegroundColor White
Write-Host 'Если Unreal Engine 5 сейчас открыт, просто нажмите кнопку [Update] вверху' -ForegroundColor Gray
Write-Host 'окна плагина или перезапустите панель ComfyUI PBR.' -ForegroundColor Gray
Write-Host '============================================================================' -ForegroundColor Cyan
