@echo off
rem Started by 4_autodetect_console.bat in its own window. Do not run directly.
cd /d "%~dp0"
call _openocd.bat
%OPENOCD% -c "init" -c "rtt setup 0x20000000 0x2000 {SEGGER RTT}" -c "rtt start" -c "rtt server start 9090 0"
echo.
echo ***** OpenOCD stopped. Copy everything above and send it to Claude. *****
pause
