@echo off
rem Builds every platform this machine can produce. Commands: see docs/BUILD.md.
rem   Windows : native, one-file exe -> build\output\windows\AchievementsManager.exe
rem   Linux   : only from WSL        -> build\output\linux\AchievementsManager
rem   macOS   : only on a Mac        -> build\output\macos\AchievementsManager.app
rem PyInstaller does not cross-compile: a .bat on Windows cannot produce Linux or macOS binaries.
setlocal
set "HERE=%~dp0"
set "SRC=%HERE:~0,-1%"
cd /d "%HERE%"

where python >nul 2>&1
if errorlevel 1 (
  echo python is not in PATH.
  exit /b 1
)

python -c "import tkinter" 2>nul
if errorlevel 1 (
  echo This python has no tkinter.
  exit /b 1
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo Installing PyInstaller...
  python -m pip install --quiet --upgrade pyinstaller
  if errorlevel 1 exit /b 1
)

rem Pillow draws covers and icons; without it the app still runs, degraded.
python -c "import PIL" 2>nul
if errorlevel 1 python -m pip install --quiet --upgrade pillow

set "FAILED="
set "WIN="
set "LINUX="

echo.
echo === Windows ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name AchievementsManager ^
  --distpath "%HERE%build\output\windows" ^
  --workpath "%HERE%build\work" ^
  --specpath "%HERE%build" ^
  "%HERE%achievements_manager.py"
if errorlevel 1 goto :windows_failed
set "WIN=%HERE%build\output\windows\AchievementsManager.exe"
echo OK: %WIN%
goto :linux

:windows_failed
echo FAILED: Windows.
set "FAILED=1"

:linux
echo.
echo === Linux ===
rem The /mnt/c/... path avoids reading wslpath output, which is UTF-16.
set "DRIVE=%SRC:~0,1%"
set "REST=%SRC:~2%"
set "LINUXPATH=/mnt/%DRIVE%/%REST:\=/%"
rem Checked in the registry: wsl.exe prints its "no distribution" notice on the console.
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss" /v DefaultDistribution >nul 2>&1
if errorlevel 1 goto :linux_skip
wsl.exe bash -lc "cd '%LINUXPATH%' && python3 -c 'import tkinter'" >nul 2>&1
if errorlevel 1 goto :linux_skip
wsl.exe bash -lc "cd '%LINUXPATH%' && python3 -m PyInstaller --noconfirm --clean --onefile --name AchievementsManager --distpath build/output/linux --workpath build/work --specpath build achievements_manager.py"
if errorlevel 1 goto :linux_failed
set "LINUX=%HERE%build\output\linux\AchievementsManager"
echo OK: %LINUX%
goto :mac

:linux_skip
echo Skipped: no usable WSL distribution ^(no default one, or its python3 has no tkinter^).
echo          On Linux: ./build-linux.sh  ^(see docs/BUILD.md^).
goto :mac

:linux_failed
echo FAILED: Linux.
set "FAILED=1"

:mac
echo.
echo === macOS ===
echo Skipped: a .app bundle is built on a Mac ^(./build-mac.sh^).

echo.
if defined WIN echo windows: %WIN%
if defined LINUX echo linux:   %LINUX%
if defined FAILED (
  echo At least one build failed.
  exit /b 1
)
exit /b 0
