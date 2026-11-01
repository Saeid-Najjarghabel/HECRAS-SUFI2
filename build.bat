@echo off
REM Build HECRAS-SUFI2.exe and the Windows installer.
REM Requires: Python 3.11+ (python.org) and Inno Setup 6 (jrsoftware.org/isinfo.php).
setlocal
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller pillow || goto :error
python packaging\make_assets.py || goto :error
pyinstaller --noconfirm --clean packaging\HECRAS_SUFI2.spec || goto :error
echo.
echo Application built: dist\HECRAS-SUFI2\HECRAS-SUFI2.exe
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% packaging\installer.iss || goto :error
  echo Installer built: dist\installer\HECRAS-SUFI2-Setup-1.1.0.exe
) else (
  echo Inno Setup 6 not found - skipping installer. The app folder above runs as-is.
)
goto :eof
:error
echo BUILD FAILED
exit /b 1
