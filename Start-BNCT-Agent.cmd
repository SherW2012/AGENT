@echo off
setlocal
set "APP_ROOT=%~dp0"
set "PYTHONW=%APP_ROOT%.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=D:\wsr\tools\python\pythonw.exe"
if not exist "%PYTHONW%" (
  echo Python GUI runtime not found. Create .venv or update Start-BNCT-Agent.cmd.
  pause
  exit /b 1
)
start "BNCT TPS Agent" "%PYTHONW%" -m bnct_tps_agent.web_server --root "%APP_ROOT:~0,-1%" --open-browser
endlocal
