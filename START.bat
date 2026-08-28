@echo off
title Itqan
cd /d "%~dp0"

echo.
echo   Itqan - starting
echo.

REM Bind to all interfaces so a phone on the same WiFi can reach the trainee
REM screen. Windows may ask to allow Python through the firewall - say yes,
REM and tick "Private networks" only.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
  if not defined LANIP set LANIP=%%a
)
set LANIP=%LANIP: =%

start "" http://localhost:8000/c/

echo   You  (coach)   : http://localhost:8000/c/
echo   Trainee, phone : http://%LANIP%:8000/t/
echo.
echo   Leave this window open during calls. Close it to stop.
echo.

python server\standalone.py --port 8000 --host 0.0.0.0
pause
