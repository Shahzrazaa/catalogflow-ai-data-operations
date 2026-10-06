@echo off
setlocal
cd /d "%~dp0"
title CatalogFlow AI

echo Starting CatalogFlow AI...
echo.

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 was not found. Install Python and run again.
    pause
    exit /b 1
  )
)

echo Checking Excel export packages...
py -c "import pandas,openpyxl" >nul 2>nul
if errorlevel 1 (
  echo Installing pandas and openpyxl...
  py -m pip install --quiet pandas openpyxl
)

if exist ".port" del /q ".port" >nul 2>nul
start "" /b pyw "%~dp0server.pyw"

for /l %%I in (1,1,30) do (
  if exist ".port" goto OPENAPP
  timeout /t 1 /nobreak >nul
)

echo CatalogFlow did not start correctly.
pause
exit /b 1

:OPENAPP
set /p APPPORT=<".port"
start "" "http://127.0.0.1:%APPPORT%"
exit /b 0
