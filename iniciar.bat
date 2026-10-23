@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Rode instalar.bat primeiro.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m jarvis
