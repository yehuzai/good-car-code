#!/usr/bin/env bash
# 打包 GoodCarCode.app（macOS）。需要 Python 3.9+ 且带 tkinter，以及 tesseract。
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-python3}"
"$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

if ! command -v tesseract >/dev/null 2>&1; then
  echo "找不到 tesseract，先执行：brew install tesseract" >&2
  exit 1
fi
TESSERACT="$(command -v tesseract)"
TESSDATA="$(cd "$(dirname "$TESSERACT")/../share/tessdata" 2>/dev/null && pwd || true)"
if [ -z "$TESSDATA" ] || [ ! -f "$TESSDATA/eng.traineddata" ]; then
  echo "找不到 tessdata（至少需要 eng.traineddata）" >&2
  exit 1
fi

# 只带英文与版面数据，控制体积
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/tessdata"
cp "$TESSDATA/eng.traineddata" "$STAGE/tessdata/"
if [ -f "$TESSDATA/osd.traineddata" ]; then
  cp "$TESSDATA/osd.traineddata" "$STAGE/tessdata/"
fi

pyinstaller --noconfirm --clean --windowed \
  --name GoodCarCode \
  --osx-bundle-identifier com.local.GoodCarCode \
  --add-binary "$TESSERACT:tesseract" \
  --add-data "$STAGE/tessdata:tesseract/tessdata" \
  app.py

echo
echo "完成。产物：dist/GoodCarCode.app"
echo "自检：dist/GoodCarCode.app/Contents/MacOS/GoodCarCode --selftest --require-bundled"
