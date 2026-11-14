@echo off
rem STEP 7 - flash the REAL firmware onto the board that is connected to the ST-Link.
cd /d "%~dp0"
call _openocd.bat
echo.
echo   1 = e235_single_usart1  RECOMMENDED, flash on BOTH boards. Each board is driven by the ESP32
echo                           through its own 4-pin master-slave plug (no soldering).
echo   2 = e235_master         master board: ESP32 on PB6/PB7 pads + slave via cable (pads need soldering!)
echo   3 = e235_slave          slave board for option 2
echo   4 = e235_single_uart    one board, ESP32 on PB6/PB7 pads (pads need soldering!)
echo.
set /p N=Which one (1-4)?
if "%N%"=="1" set "F=e235_single_usart1.bin"
if "%N%"=="2" set "F=e235_master.bin"
if "%N%"=="3" set "F=e235_slave.bin"
if "%N%"=="4" set "F=e235_single_uart.bin"
if not defined F (echo Invalid choice & pause & exit /b)
echo.
echo === Flashing %F% ===
%OPENOCD% -c "init" -c "reset halt" -c "stm32f1x mass_erase 0" -c "program %F% 0x08000000 verify reset exit"
echo.
if errorlevel 1 (echo ***** FLASH FAILED - hold the wires and try again *****) else (echo ***** %F% FLASHED OK *****)
echo.
pause
