@echo off
rem STEP 2 - UNLOCK. Removes read protection. THIS ERASES THE FACTORY FIRMWARE.
rem Uses gd32_unlock from gd32e23x_tools.tcl (follows GigaDevice's SDK), not "stm32f1x unlock".
cd /d "%~dp0"
call _openocd.bat
echo.
echo  WARNING: this permanently erases the factory firmware on this board.
echo  Make sure step 0 said CONNECTED OK, and the wires are held still.
echo.
set /p OK=Type YES (capital letters) and press ENTER to continue:
if not "%OK%"=="YES" (echo Cancelled. Nothing was changed. & pause & exit /b)
echo.
%OPENOCD% -c "init" -c "halt" -c "gd32_status" -c "gd32_unlock" -c "exit"
echo.
if errorlevel 1 (echo ***** UNLOCK FAILED - keep holding the wires and run this again. Send the output to Claude. *****) else (
  echo ***** UNLOCK DONE *****
  echo NOW: unplug the ST-Link from the laptop USB, wait 5 seconds, plug it back in.
  echo Then run 0_test_connection.bat again - it should say PROTECTION : OFF
)
echo.
pause
