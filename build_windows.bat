@echo off
REM Build GoodCarCode.exe on Windows. Needs Python 3.9+ with tkinter.
setlocal
cd /d "%~dp0"

py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean --windowed --onefile ^
  --name GoodCarCode ^
  app.py

echo.
echo Done. Executable: dist\GoodCarCode.exe
endlocal
