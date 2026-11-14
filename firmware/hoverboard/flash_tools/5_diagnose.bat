@echo off
rem STEP 5 - READ ONLY diagnosis. Changes nothing on the chip.
cd /d "%~dp0"
call _openocd.bat
%OPENOCD% -c "init" -c "gd32_diag" -c "exit"
echo.
echo ***** Copy everything above and send it to Claude *****
pause
