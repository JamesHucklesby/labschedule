#!/usr/bin/env bash
# Sets up a Python virtual environment in WSL and installs project dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Checking Python 3..."
if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found. Installing..."
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv
fi

echo "==> Creating virtual environment (.venv-wsl)..."
python3 -m venv .venv-wsl

echo "==> Activating virtual environment..."
# shellcheck disable=SC1091
source .venv-wsl/bin/activate

echo "==> Upgrading pip..."
pip install --upgrade pip --quiet

echo "==> Installing dependencies from requirements.txt..."
pip install -r requirements.txt

echo ""
echo "Setup complete. Run the app with: ./run.sh"
