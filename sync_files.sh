#!/usr/bin/env bash
# One-click setup + run for course_sync.py (Linux/macOS).
# Usage: ./sync_files.sh
set -euo pipefail

VENV_DIR=".venv"
REQUIREMENTS="requirements.txt"

echo
echo "=== 1. Verificando Python ==="
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 no se encontró en el PATH."
    exit 1
fi
python3 --version

echo
echo "=== 2. Entorno Virtual ($VENV_DIR) ==="
if [ -d "$VENV_DIR" ]; then
    echo " Usando entorno virtual existente"
else
    python3 -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo
echo "=== 3. Actualizando dependencias ==="
python -m pip install --upgrade pip
if [ -f "$REQUIREMENTS" ]; then
    pip install -r "$REQUIREMENTS"
else
    echo "ERROR: No se encontró el archivo de requisitos."
    exit 1
fi
python -m playwright install chromium

echo
echo "=== 4. Corriendo sincronización de Archivos ==="
python course_sync.py
