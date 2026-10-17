@echo off
REM Build GoodCarCode.exe on Windows.
REM Needs Python 3.9+ with tkinter, and Tesseract-OCR installed (default path below).
setlocal
cd /d "%~dp0"

py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

set "TESS=C:\Program Files\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" (
  echo Cannot find "%TESS%\tesseract.exe" - install Tesseract-OCR or edit TESS above.>&2
  exit /b 1
)

REM Stage tesseract (keeps tesseract.exe next to its DLLs) and trim tessdata.
if exist .tesseract-bundle rmdir /s /q .tesseract-bundle
xcopy /E /I /Y /Q "%TESS%" ".tesseract-bundle" >nul
for %%f in (".tesseract-bundle\tessdata\*.traineddata") do (
  if /i not "%%~nxf"=="eng.traineddata" if /i not "%%~nxf"=="osd.traineddata" del /q "%%f"
)

pyinstaller --noconfirm --clean --windowed --onefile ^
  --name GoodCarCode ^
  --add-data ".tesseract-bundle;tesseract" ^
  app.py

echo.
echo Done. Executable: dist\GoodCarCode.exe
echo Self test: set PLATE_SELFTEST_LOG=selftest.log ^&^& dist\GoodCarCode.exe --selftest --require-bundled
endlocal
