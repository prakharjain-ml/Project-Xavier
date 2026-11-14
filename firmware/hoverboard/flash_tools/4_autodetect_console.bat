@echo off
rem STEP 4 - Opens the autodetect console. Board must be powered by the CHARGER,
rem ST-Link connected with ONLY GND, SWDIO, SWCLK (3.3V wire removed).
rem Window 1 (OpenOCD) carries the text; window 2 (this one) is where you read and type.
cd /d "%~dp0"
start "OpenOCD RTT - leave this open" cmd /c _rtt_server.bat
timeout /t 3 /nobreak >nul
python rtt_console.py
pause
