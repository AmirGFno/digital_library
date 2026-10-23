@echo off
REM Build the Windows executable (run from the project root).
setlocal

cd /d "%~dp0"

echo [1/3] Installing dependencies...
python -m pip install -r requirements-dev.txt || goto :error

echo [2/3] Running tests...
python -m pytest -q || goto :error

echo [3/3] Building DigitalLibrary.exe...
python -m PyInstaller --noconfirm --clean DigitalLibrary.spec || goto :error

echo.
echo Build finished: dist\DigitalLibrary.exe
pause
exit /b 0

:error
echo.
echo Build failed. Check the messages above.
pause
exit /b 1
