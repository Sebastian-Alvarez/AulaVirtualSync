#!/usr/bin/env bash
# One-click setup + run for course_sync.py (Linux/macOS).
# Usage: ./sync_files.sh
set -euo pipefail

VENV_DIR=".venv"
REQUIREMENTS="requirements.txt"

echo
echo "=== 1. Checking Python ==="
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 was not found on PATH."
    exit 1
fi
python3 --version

echo
echo "=== 2. Creating virtual environment ($VENV_DIR) ==="
if [ -d "$VENV_DIR" ]; then
    echo "Virtual environment already exists, skipping creation."
else
    python3 -m venv "$VENV_DIR"
fi

echo
echo "=== 3. Activating virtual environment ==="
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo
echo "=== 4. Upgrading pip ==="
python -m pip install --upgrade pip

echo
echo "=== 5. Installing dependencies ==="
if [ -f "$REQUIREMENTS" ]; then
    pip install -r "$REQUIREMENTS"
else
    echo "ERROR: requirements.txt not found."
    exit 1
fi

echo
echo "=== 6. Installing Playwright browser (Chromium) ==="
python -m playwright install chromium

echo
echo "=== 7. Running course sync ==="
python course_sync.py
