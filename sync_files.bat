@echo off
REM ============================================
REM  One-click setup + run for course_sync.py
REM  Usage: double-click, or "sync_files.bat" in cmd
REM ============================================
setlocal

set VENV_DIR=.venv
set REQUIREMENTS=requirements.txt

echo.
echo === 1. Verificando Python ===
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: No se encontró Python en el PATH.
    pause
    exit /b 1
)
python --version

echo.
echo === 2. Entorno Virtual (%VENV_DIR%) ===
if exist %VENV_DIR% (
    echo Usando entorno virtual existente: %VENV_DIR%
) else (
    python -m venv %VENV_DIR%
)
call %VENV_DIR%\Scripts\activate.bat

echo.
echo === 3. Actualizando dependencias ===
python -m pip install --upgrade pip
if exist %REQUIREMENTS% (
    pip install -r %REQUIREMENTS% | findstr /v /i "already satisfied"
) else (
    echo ERROR: No se encontró el archivo de requisitos: %REQUIREMENTS%
    pause
    exit /b 1
)
python -m playwright install chromium

echo.
echo === 4. Corriendo sincronización de Archivos ===
python course_sync.py
pause

endlocal
