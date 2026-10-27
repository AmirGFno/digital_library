@echo off
REM Glib - Run Script
echo ========================================
echo     Glib Application
echo ========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python 3.7 or later from python.org
    pause
    exit /b 1
)

REM Check if requirements are installed
echo Checking dependencies...
python -c "import PyQt6, PIL, fitz" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies!
        pause
        exit /b 1
    )
    echo Dependencies installed successfully.
) else (
    echo All dependencies are already installed.
)

REM Run the application
echo.
echo Starting Glib...
echo ========================================
echo.
python main.py

REM If the application crashes
if errorlevel 1 (
    echo.
    echo ERROR: Application crashed with code %errorlevel%
    echo.
    echo Troubleshooting:
    echo 1. Make sure all dependencies are installed
    echo 2. Check logs in the 'logs' folder
    echo 3. Verify Python version (3.7+ required)
    echo.
    pause
)