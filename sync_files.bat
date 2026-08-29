@echo off
REM ============================================
REM  One-click setup + run for course_sync.py
REM  Usage: double-click, or "sync_files.bat" in cmd
REM ============================================
setlocal

set VENV_DIR=.venv
set REQUIREMENTS=requirements.txt

echo.
echo === 1. Checking Python ===
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    pause
    exit /b 1
)
python --version

echo.
echo === 2. Creating virtual environment (%VENV_DIR%) ===
if exist %VENV_DIR% (
    echo Virtual environment already exists, skipping creation.
) else (
    python -m venv %VENV_DIR%
)

echo.
echo === 3. Activating virtual environment ===
call %VENV_DIR%\Scripts\activate.bat

echo.
echo === 4. Upgrading pip ===
python -m pip install --upgrade pip

echo.
echo === 5. Installing dependencies ===
if exist %REQUIREMENTS% (
    pip install -r %REQUIREMENTS% | findstr /v /i "already satisfied"
) else (
    echo ERROR: requirements.txt not found.
    pause
    exit /b 1
)

echo.
echo === 6. Installing Playwright browser (Chromium) ===
python -m playwright install chromium

echo.
echo === 7. Running course sync ===
python course_sync.py
pause

endlocal
