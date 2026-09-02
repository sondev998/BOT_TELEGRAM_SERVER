@echo off
setlocal
title Antigravity Telegram Bot Server
color 0A

echo ========================================================
echo        ANTIGRAVITY TELEGRAM CONTROLLER SERVER
echo ========================================================
echo.

cd /d "%~dp0"

:: Set UTF-8 encoding
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Check Python
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay Python tren he thong!
    echo Vui long cai dat Python 3.10 tro len va tich vao Add Python to PATH.
    goto :end
)

:: Install requirements
echo [*] Kiem tra thu vien phu thuoc...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

:: Tu dong dung cac phien bot cu de tranh loi 409 Conflict
echo [*] Kiem tra va dong cac tien trinh bot cu...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo [*] Dang khoi dong Telegram Bot...
echo.
python bot.py

:end
echo.
echo ========================================================
echo Nhan phim bat ky de thoat...
echo ========================================================
pause
