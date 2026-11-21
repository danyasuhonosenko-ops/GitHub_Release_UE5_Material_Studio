<# :
@echo off
chcp 65001 >nul
title AI PBR Studio - One-Click UE5 Uninstaller
set "BAT_FILE=%~f0"
set "TARGET_DIR=%~1"
powershell -NoProfile -Sta -ExecutionPolicy Bypass -Command "Invoke-Expression ([System.IO.File]::ReadAllText($env:BAT_FILE, [System.Text.Encoding]::UTF8))"
echo.
pause
exit /b
#>

Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host '  AI PBR & Substance Studio for Unreal Engine 5' -ForegroundColor White
Write-Host '  Automated Plugin Uninstaller (Удаление плагина из проекта UE5)' -ForegroundColor Gray
Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host ''

$ErrorActionPreference = 'Continue'
$target = $env:TARGET_DIR

if (-not $target -or -not (Test-Path $target)) {
    Add-Type -AssemblyName System.Windows.Forms
    $top = New-Object System.Windows.Forms.Form
    $top.TopMost = $true
    $top.StartPosition = 'CenterScreen'
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = 'Выберите корневую папку проекта Unreal Engine 5 (где лежит .uproject) для удаления плагина AI PBR Studio'
    $dlg.ShowNewFolderButton = $false
    if ($dlg.ShowDialog($top) -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host '[Отменено пользователем]' -ForegroundColor Yellow
        exit 1
    }
    $target = $dlg.SelectedPath
}

if (Test-Path $target -PathType Leaf) {
    $target = Split-Path $target -Parent
}

$contentDir = Join-Path $target 'Content'
$widgetDirs = @(
    @{ Name = 'AIPBR_Studio_Plugin'; Path = (Join-Path $contentDir 'AIPBR_Studio_Plugin') },
    @{ Name = 'ConfyUI_plagin';      Path = (Join-Path $contentDir 'ConfyUI_plagin') }
)
$pyDir = Join-Path $contentDir 'Python'
$removedCount = 0

foreach ($f in @('comfy_to_ue.py','comfy_to_ue.py.ota_tmp','comfy_to_corona.py','presets_data.py','UE_plagin.json','init_unreal.py')) {
    $p = Join-Path $pyDir $f
    if (Test-Path $p) {
        Remove-Item $p -Force -ErrorAction SilentlyContinue
        $removedCount++
        Write-Host ('  [-] Удалён: Content\Python\' + $f) -ForegroundColor Gray
    }
}

$pycDir = Join-Path $pyDir '__pycache__'
if (Test-Path $pycDir) {
    Get-ChildItem -Path $pycDir -Filter '*comfy*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $pycDir -Filter '*presets_data*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}

foreach ($wd in $widgetDirs) {
    $panelAsset = Join-Path $wd.Path 'BP_ComfyPanel.uasset'
    if (Test-Path $panelAsset) {
        Remove-Item $panelAsset -Force -ErrorAction SilentlyContinue
        $removedCount++
        Write-Host ('  [-] Удалён: Content\' + $wd.Name + '\BP_ComfyPanel.uasset') -ForegroundColor Gray
    }
    if ((Test-Path $wd.Path) -and @(Get-ChildItem -Path $wd.Path -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item $wd.Path -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ''
Write-Host '============================================================================' -ForegroundColor Cyan
if ($removedCount -gt 0) {
    Write-Host ('[ГОТОВО] Плагин AI PBR & Substance Studio успешно удалён из проекта (' + $removedCount + ' файлов).') -ForegroundColor Green
} else {
    Write-Host '[i] Файлы плагина в выбранной папке проекта не обнаружены (возможно, уже удалены).' -ForegroundColor Yellow
}
Write-Host ('  -> Проект: ' + $target) -ForegroundColor White
Write-Host '  * Все ранее созданные вами материалы и текстуры в Content/Textures/ComfyUI сохранены.' -ForegroundColor Gray
Write-Host '============================================================================' -ForegroundColor Cyan
