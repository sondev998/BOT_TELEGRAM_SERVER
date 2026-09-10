@echo off
setlocal
title Stop Antigravity Telegram Bot
color 0C

echo ========================================================
echo        DANG DUNG ANTIGRAVITY TELEGRAM BOT
echo ========================================================
echo.

cd /d "%~dp0"

:: Đóng tiến trình python chạy bot.py
python -c "import os, psutil; [p.kill() for p in psutil.process_iter(['pid','cmdline']) if p.pid != os.getpid() and any('bot.py' in str(arg) for arg in (p.info['cmdline'] or []))]" 2>nul

echo.
echo [*] Da dung tat ca cac tien trinh Bot thanh cong!
timeout /t 2 >nul
