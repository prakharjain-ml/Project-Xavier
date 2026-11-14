@echo off
rem STEP 0 - READ ONLY. Changes nothing on the board. Safe to run as often as you like.
cd /d "%~dp0"
call _openocd.bat
echo.
echo === Testing ST-Link connection to the hoverboard chip (read only) ===
echo.
%OPENOCD% -c "init" -c "halt" -c "gd32_status" -c "exit"
echo.
if errorlevel 1 (echo ***** FAILED - copy everything above and send it to Claude *****) else (echo ***** CONNECTED OK - copy everything above and send it to Claude *****)
echo.
pause
