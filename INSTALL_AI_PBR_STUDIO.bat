@echo off
chcp 65001 >nul
title AI PBR & Substance Studio — One-Click UE5 Client Installer
echo ============================================================================
echo   AI PBR ^& Substance Studio for Unreal Engine 5 (5.3 - 5.7+)
echo   Automated Client Installer
echo ============================================================================
echo.

set "SRC_DIR=%~dp0"
set "TARGET_DIR=%~1"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; " ^
  "$src = '%SRC_DIR%'; " ^
  "$target = '%TARGET_DIR%'; " ^
  "if (-not $target -or -not (Test-Path $target)) { " ^
  "  Add-Type -AssemblyName System.Windows.Forms; " ^
  "  $dlg = New-Object System.Windows.Forms.FolderBrowserDialog; " ^
  "  $dlg.Description = 'Выберите корневую папку вашего проекта Unreal Engine 5 (где находится файл .uproject)'; " ^
  "  $dlg.ShowNewFolderButton = $false; " ^
  "  if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host '[Отменено пользователем]' -ForegroundColor Yellow; exit 1 } " ^
  "  $target = $dlg.SelectedPath; " ^
  "} " ^
  "if (Test-Path $target -PathType Leaf) { $target = Split-Path $target -Parent } " ^
  "$uproj = Get-ChildItem -Path $target -Filter '*.uproject' -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
  "if (-not $uproj) { Write-Host '[!] В выбранной папке не найден файл .uproject, но установка в Content/ будет выполнена.' -ForegroundColor Yellow } " ^
  "$contentDir = Join-Path $target 'Content'; " ^
  "$widgetDir = Join-Path $contentDir 'ConfyUI_plagin'; " ^
  "$pyDir = Join-Path $contentDir 'Python'; " ^
  "New-Item -ItemType Directory -Force -Path $widgetDir | Out-Null; " ^
  "New-Item -ItemType Directory -Force -Path $pyDir | Out-Null; " ^
  "Copy-Item (Join-Path $src 'Content\ConfyUI_plagin\BP_ComfyPanel.uasset') (Join-Path $widgetDir 'BP_ComfyPanel.uasset') -Force; " ^
  "foreach ($f in @('comfy_to_ue.py','comfy_to_corona.py','presets_data.py','UE_plagin.json','UE_plagin_chord.json','init_unreal.py')) { " ^
  "  $p = Join-Path $src $f; if (Test-Path $p) { Copy-Item $p (Join-Path $pyDir $f) -Force } " ^
  "} " ^
  "$licFile = Join-Path $pyDir 'studio_license_state.json'; " ^
  "if (Test-Path $licFile) { Remove-Item $licFile -Force -ErrorAction SilentlyContinue } " ^
  "if ($uproj) { " ^
  "  try { " ^
  "    $j = Get-Content $uproj.FullName -Raw -Encoding UTF8 | ConvertFrom-Json; " ^
  "    if (-not $j.Plugins) { $j | Add-Member -NotePropertyName 'Plugins' -NotePropertyValue @() } " ^
  "    foreach ($reqPlug in @('PythonScriptPlugin','EditorScriptingUtilities')) { " ^
  "      $found = $j.Plugins | Where-Object { $_.Name -eq $reqPlug }; " ^
  "      if (-not $found) { $j.Plugins += [PSCustomObject]@{ Name = $reqPlug; Enabled = $true } } else { $found.Enabled = $true } " ^
  "    } " ^
  "    $j | ConvertTo-Json -Depth 10 | Set-Content $uproj.FullName -Encoding UTF8; " ^
  "    Write-Host ('[OK] Плагины PythonScriptPlugin и EditorScriptingUtilities активированы в ' + $uproj.Name) -ForegroundColor Green; " ^
  "  } catch {} " ^
  "} " ^
  "Write-Host ''; " ^
  "Write-Host '============================================================================' -ForegroundColor Cyan; " ^
  "Write-Host '[ГОТОВО] AI PBR & Substance Studio успешно установлен в проект:' -ForegroundColor Green; " ^
  "Write-Host ('  -> ' + $target) -ForegroundColor White; " ^
  "Write-Host 'При следующем открытии проекта в Unreal Engine 5 на верхней панели' -ForegroundColor Gray; " ^
  "Write-Host 'автоматически появится кнопка ComfyUI PBR и ваш индивидуальный Copy ID!' -ForegroundColor Gray; " ^
  "Write-Host '============================================================================' -ForegroundColor Cyan;"

echo.
pause
