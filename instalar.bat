@echo off
cd /d "%~dp0"
py -3.13 -m venv .venv || goto :erro
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :erro
echo.
echo Pronto! Abra o Vektor com iniciar.bat
pause
exit /b 0
:erro
echo Falha na instalacao. Voce precisa do Python 3.13 (py install 3.13).
pause
exit /b 1
