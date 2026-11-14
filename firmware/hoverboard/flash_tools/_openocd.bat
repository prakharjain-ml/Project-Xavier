@echo off
rem Shared settings - the numbered scripts call this. Do not run it directly.
rem Needs xPack OpenOCD 0.12.0-7 (older builds do not know GD32E23x). Looked for in:
rem   1) ..\tools\xpack-openocd-0.12.0-7               (repo layout: firmware\hoverboard\tools\)
rem   2) ..\firmware_ref\openocd_new\xpack-openocd-0.12.0-7   (Keshav's original working folder)
rem FLASH_SIZE: GD32E235 has 64 KB; the chip's size register cannot be trusted.
set "OCD=%~dp0..\tools\xpack-openocd-0.12.0-7"
if not exist "%OCD%\bin\openocd.exe" set "OCD=%~dp0..\firmware_ref\openocd_new\xpack-openocd-0.12.0-7"
if not exist "%OCD%\bin\openocd.exe" (
  echo.
  echo ***** OpenOCD not found. Download xpack-openocd-0.12.0-7-win32-x64.zip from
  echo ***** https://github.com/xpack-dev-tools/openocd-xpack/releases/tag/v0.12.0-7
  echo ***** and unzip it so that this file exists:
  echo *****   %~dp0..\tools\xpack-openocd-0.12.0-7\bin\openocd.exe
  echo.
)
set OPENOCD="%OCD%\bin\openocd.exe" -s "%OCD%\openocd\scripts" -f interface/stlink.cfg -c "transport select swd" -c "set CPUTAPID 0" -c "set FLASH_SIZE 0x10000" -f target/gd32e23x.cfg -f gd32e23x_tools.tcl
