@echo off
rem おたより工房 ローカル版の起動。初回だけ .venv を作って anthropic を入れる。
setlocal
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
  echo [1/2] .venv を作ります...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  if not exist "%PY%" (
    echo venv を作れませんでした。Python 3.10 以降を入れてください。
    pause
    exit /b 1
  )
  echo [2/2] anthropic を入れます...
  "%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
)

"%PY%" server.py %*
endlocal
