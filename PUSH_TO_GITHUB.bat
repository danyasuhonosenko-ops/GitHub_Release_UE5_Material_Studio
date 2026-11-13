@echo off
chcp 65001 >nul
title Push AI PBR & Substance Studio + Cluster Config to GitHub
cd /d "%~dp0"
if exist "D:\AI\MyAiAssistant\license_tools\render_cluster_config.json" (
    copy /Y "D:\AI\MyAiAssistant\license_tools\render_cluster_config.json" "%~dp0render_cluster_config.json" >nul
)
git add -A
git commit -m "Update AI PBR & Substance Studio client package and dynamic GPU cluster config"
git branch -M main
git remote -v | findstr "origin" >nul
if errorlevel 1 (
    echo.
    echo [!] Укажите URL вашего репозитория GitHub (например: https://github.com/DaniilSukhnosenko/UE5-PBR-Material-Studio.git):
    set /p REPO_URL="GitHub Repo URL: "
    git remote add origin "%REPO_URL%"
)
git push -u origin main
echo.
echo [OK] Синхронизация с GitHub завершена!
pause
