@echo off
REM Build the Windows executable (run from the project root).
setlocal

cd /d "%~dp0"

echo [1/4] Installing dependencies...
python -m pip install -r requirements-dev.txt || goto :error

echo [2/4] Running tests...
python -m pytest -q || goto :error

echo [3/4] Building the portable executable...
python -m PyInstaller --noconfirm --clean DigitalLibrary.spec || goto :error

echo [4/4] Building the installed folder edition...
python -m PyInstaller --noconfirm --clean --distpath dist\installed DigitalLibraryInstalled.spec || goto :error

echo.
echo Build finished:
echo   dist\DigitalLibrary.exe                  (portable)
echo   dist\installed\DigitalLibrary\          (installed edition)
echo Run installer\build_installer.bat to make the setup program (needs NSIS).
pause
exit /b 0

:error
echo.
echo Build failed. Check the messages above.
pause
exit /b 1
