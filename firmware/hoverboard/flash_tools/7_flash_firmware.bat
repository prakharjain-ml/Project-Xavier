@echo off
rem STEP 7 - flash the REAL firmware: master, slave, or single (master board alone + ESP32)
cd /d "%~dp0"
call _openocd.bat
echo.
echo   1 = e235_single_uart  (master board ALONE, controlled by ESP32 - test this first)
echo   2 = e235_master       (master board, ESP32 + slave via original cable)
echo   3 = e235_slave        (slave board)
echo.
set /p N=Which one (1-3)?
if "%N%"=="1" set "F=e235_single_uart.bin"
if "%N%"=="2" set "F=e235_master.bin"
if "%N%"=="3" set "F=e235_slave.bin"
if not defined F (echo Invalid choice & pause & exit /b)
echo.
echo === Flashing %F% ===
%OPENOCD% -c "init" -c "reset halt" -c "stm32f1x mass_erase 0" -c "program %F% 0x08000000 verify reset exit"
echo.
if errorlevel 1 (echo ***** FLASH FAILED - hold the wires and try again *****) else (echo ***** %F% FLASHED OK *****)
echo.
pause
