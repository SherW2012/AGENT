\xef\xbb\xbf# Build a distributable Windows package of BNCT TPS Agent.
#
# Run this ON WINDOWS from the repository root:
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Output: dist\BNCT-Agent\ (folder you can copy anywhere) and
#         dist\BNCT-Agent-win64.zip (the file you hand to colleagues).
#
# Requirements on the build machine only: Python 3.10+ and internet access
# (to fetch pyinstaller). Colleagues' machines need NOTHING preinstalled.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "== 1/5 Creating isolated build environment =="
if (Test-Path ".venv-build") { Remove-Item ".venv-build" -Recurse -Force }
python -m venv .venv-build
$py = ".\.venv-build\Scripts\python.exe"
& $py -m pip install --upgrade pip -q
& $py -m pip install . pyinstaller -q

Write-Host "== 2/5 Building executable with PyInstaller =="
if (Test-Path "dist\BNCT-Agent") { Remove-Item "dist\BNCT-Agent" -Recurse -Force }
& $py -m PyInstaller --noconfirm --clean --onedir --console `
    --name "BNCT-Agent" `
    --add-data "src/bnct_tps_agent/web;bnct_tps_agent/web" `
    --collect-all openai `
    packaging/launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "== 3/5 Bundling skills and sample data =="
Copy-Item -Recurse -Force "skills" "dist\BNCT-Agent\skills"
Copy-Item -Recurse -Force "sample_data" "dist\BNCT-Agent\sample_data"
Copy-Item -Force ".env.example" "dist\BNCT-Agent\.env.example"

Write-Host "== 4/5 Writing user-facing files =="
@"
BNCT TPS Agent 使用说明
=======================

1. 双击 BNCT-Agent.exe 启动（会弹出一个控制台窗口并自动打开浏览器）。
   如果浏览器没有自动打开，把控制台里显示的 http://127.0.0.1:8765/#token=... 整行
   复制到浏览器打开（必须带 #token= 部分）。

2. 首次使用：点左下角「设置」，选择模型供应商（国内推荐 DeepSeek 或 Kimi），
   填入你自己的 API Key，保存即可开始对话。
   - Key 只保存在本机运行的进程里，不写盘、不外传。
   - Kimi 支持图片识别；DeepSeek 为纯文本。

3. 工作目录默认是本文件夹下的 workspace\，可在设置中切换到任意工程目录。
   会话历史、导入的 skill、定时任务保存在 %USERPROFILE%\.bnct_agent\。

4. 关闭控制台窗口即退出服务。

注意：本工具是研发辅助工具，不是医疗器械；所有输出必须由有资质人员复核。
"@ | Out-File -FilePath "dist\BNCT-Agent\使用说明.txt" -Encoding utf8

@"
@echo off
start "" "%~dp0BNCT-Agent.exe"
"@ | Out-File -FilePath "dist\BNCT-Agent\启动-BNCT-Agent.cmd" -Encoding ascii

Write-Host "== 5/5 Zipping =="
if (Test-Path "dist\BNCT-Agent-win64.zip") { Remove-Item "dist\BNCT-Agent-win64.zip" -Force }
Compress-Archive -Path "dist\BNCT-Agent" -DestinationPath "dist\BNCT-Agent-win64.zip"

Write-Host ""
Write-Host "Done. Output: dist\BNCT-Agent-win64.zip" -ForegroundColor Green
Write-Host "Unzip and double-click BNCT-Agent.exe to run."
