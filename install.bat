@echo off
setlocal
cd /d "%~dp0"
echo === VRCam Studio install ===

rem --- Python 3.12 (SpoutGL ships wheels for 3.8-3.13) ---
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 not found - installing with winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  py -3.12 --version >nul 2>&1 || (echo Python install failed. Install Python 3.12 from python.org, then re-run. & pause & exit /b 1)
)

if not exist .venv (
  py -3.12 -m venv .venv || (echo venv failed & pause & exit /b 1)
)
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || (echo pip install failed & pause & exit /b 1)

rem --- ffmpeg (gyan.dev release essentials: has nvenc / amf / qsv / ddagrab) ---
if not exist tools\ffmpeg\bin\ffmpeg.exe (
  echo Downloading ffmpeg...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Force tools | Out-Null;" ^
    "Invoke-WebRequest https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile tools\ff.zip;" ^
    "Expand-Archive tools\ff.zip tools\ff_tmp -Force;" ^
    "$d = Get-ChildItem tools\ff_tmp -Directory | Select-Object -First 1;" ^
    "Move-Item $d.FullName tools\ffmpeg; Remove-Item tools\ff.zip; Remove-Item tools\ff_tmp -Recurse -Force"
  if not exist tools\ffmpeg\bin\ffmpeg.exe (echo ffmpeg download failed & pause & exit /b 1)
)

echo.
echo Checking everything...
.venv\Scripts\python -m studio doctor
echo.
echo Done. Start the studio with run.bat
pause
