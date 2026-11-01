@echo off
setlocal
cd /d "%~dp0"
echo Welcome to NOUS. Let's get you playing.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1"
if errorlevel 1 (
  echo.
  echo NOUS could not finish. Read the message above, then double-click setup.bat to retry.
  pause
)
endlocal
