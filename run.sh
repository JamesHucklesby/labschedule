#!/usr/bin/env bash
# Activates the WSL virtual environment and starts the lab schedule app.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv-wsl"
WINDOWS_PYTHON="/mnt/c/Users/James/python_labschedule/.venv/Scripts/python.exe"

echo "==> Starting lab schedule app on http://localhost:8080"
if [ -x "$WINDOWS_PYTHON" ]; then
    exec "$WINDOWS_PYTHON" main.py
fi

if [ ! -d "$VENV" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
exec python3 main.py
