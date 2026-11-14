@echo off
rem STEP 6 - flash one of the 12 motor test builds (motor_tests\test01.bin .. test12.bin).
rem Each one spins the wheel slowly back and forth (zigzag, max 12% power).
rem Board powered by the CHARGER, ST-Link 3.3V wire disconnected, wheel in the air.
cd /d "%~dp0"
call _openocd.bat
echo.
set /p N=Which test number (1-12)? Type it and press ENTER:
set "NN=0%N%"
set "NN=%NN:~-2%"
if not exist "motor_tests\test%NN%.bin" (echo No such test: motor_tests\test%NN%.bin & pause & exit /b)
echo.
echo === Flashing motor_tests\test%NN%.bin ===
echo.
%OPENOCD% -c "init" -c "reset halt" -c "stm32f1x mass_erase 0" -c "program motor_tests/test%NN%.bin 0x08000000 verify reset exit"
echo.
if errorlevel 1 (echo ***** FLASH FAILED - hold the wires and try again *****) else (
  echo ***** test%NN% FLASHED - let go of the wires and WATCH THE WHEEL for 15 seconds *****
)
echo.
pause
