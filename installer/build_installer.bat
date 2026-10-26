@echo off
REM Build the Digital Library setup program from the installed folder edition.
REM Requires NSIS 3 (https://nsis.sourceforge.io) and a finished
REM "dist\installed\DigitalLibrary" folder (see build_windows.bat).
setlocal enabledelayedexpansion

cd /d "%~dp0.."

for /f %%v in ('python -c "from config import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%v
if "%VERSION%"=="" (
    echo Could not read APP_VERSION from config.py
    exit /b 1
)

set MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe
if not exist "%MAKENSIS%" set MAKENSIS=%ProgramFiles%\NSIS\makensis.exe
if not exist "%MAKENSIS%" (
    echo NSIS was not found. Install it from https://nsis.sourceforge.io
    exit /b 1
)

if not exist "dist\installed\DigitalLibrary\DigitalLibrary.exe" (
    echo The installed build is missing. Run build_windows.bat first.
    exit /b 1
)

echo Building DigitalLibrary-%VERSION%-Setup.exe ...
if not exist build\installer mkdir build\installer
"%MAKENSIS%" /DVERSION=%VERSION% "/DSRCDIR=%CD%\dist\installed\DigitalLibrary" ^
    "/DOUTFILE=%CD%\build\installer\DigitalLibrary-%VERSION%-Setup.exe" installer\DigitalLibrary.nsi
if errorlevel 1 exit /b 1

echo.
echo Setup program: build\installer\DigitalLibrary-%VERSION%-Setup.exe
