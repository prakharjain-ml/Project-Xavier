@echo off
rem STEP 8 - just keep OpenOCD connected to the board (no flashing, no RTT).
rem Needed by hall_watch.py, which reads the pins through OpenOCD's Tcl port 6666.
rem Leave this window open while hall_watch.py runs. Close it before flashing again.
cd /d "%~dp0"
call _openocd.bat
%OPENOCD% -c "init"
echo.
echo ***** OpenOCD stopped. *****
pause
