@echo off
setlocal
set "APP_ROOT=%~dp0"
set "PYTHONW=%APP_ROOT%.venv\Scripts\pythonw.exe"
if exist "%PYTHONW%" (
  start "BNCT TPS Agent" "%PYTHONW%" -m bnct_tps_agent.web_server --root "%APP_ROOT:~0,-1%" --open-browser
) else (
  rem Fall back to pythonw on PATH so the launcher is not tied to one machine.
  start "BNCT TPS Agent" pythonw -m bnct_tps_agent.web_server --root "%APP_ROOT:~0,-1%" --open-browser
)
endlocal
