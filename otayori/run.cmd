@echo off
rem Otayori Kobo (local). First run creates .venv and installs anthropic.
rem Keep this file ASCII-only with CRLF line endings: cmd.exe misreads UTF-8 / LF batch files.
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto run

echo [1/2] Creating .venv ...
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m venv .venv) else (python -m venv .venv)
if not exist "%PY%" (
  echo Could not create .venv. Please install Python 3.10 or later.
  pause
  exit /b 1
)
echo [2/2] Installing anthropic ...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt

:run
"%PY%" server.py %*
endlocal
