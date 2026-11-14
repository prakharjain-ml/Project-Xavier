@echo off
rem STEP 3 - WIPE the chip and FLASH autodetect.
rem autodetect_e235_irc.bin = built locally with PlatformIO, uses the INTERNAL clock
rem (the downloaded autodetect_e230_rtt.bin hangs on this board: it waits for an external crystal).
cd /d "%~dp0"
call _openocd.bat
echo.
echo === Erasing chip and flashing autodetect_e235_irc.bin ===
echo.
%OPENOCD% -c "init" -c "reset halt" -c "stm32f1x mass_erase 0" -c "program autodetect_e235_irc.bin 0x08000000 verify reset exit"
echo.
if errorlevel 1 (echo ***** FLASH FAILED - keep holding the wires and run this again. Send the output to Claude. *****) else (echo ***** FLASHED AND VERIFIED OK *****)
echo.
pause
