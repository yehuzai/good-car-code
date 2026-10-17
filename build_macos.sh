#!/usr/bin/env bash
# Build GoodCarCode.app for macOS. Needs Python 3.9+ with tkinter.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-python3}"
"$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean --windowed \
  --name GoodCarCode \
  --osx-bundle-identifier com.local.GoodCarCode \
  app.py

echo
echo "Done. App bundle: dist/GoodCarCode.app"
