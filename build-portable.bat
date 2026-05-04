@echo off
setlocal

cd /d "%~dp0"
set "EXIT_CODE=0"
set "PAUSE_ON_EXIT=0"
if /I "%~1"=="pause" set "PAUSE_ON_EXIT=1"

echo Close running portable from previous build...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$release = Resolve-Path 'frontend\release' -ErrorAction SilentlyContinue; if ($release) { Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($release.Path, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue }"

echo Install frontend dependencies with pnpm...
cd frontend
call corepack pnpm install
if errorlevel 1 goto ERROR

echo Build Electron portable client...
call corepack pnpm dist:win
if errorlevel 1 goto ERROR

cd ..
if not exist "backend\release" mkdir "backend\release"

echo Copy portable release to backend\release...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Copy-Item -Path 'frontend\release\Contrack-Client-*-portable.exe' -Destination 'backend\release' -Force"
if errorlevel 1 goto ERROR

echo Done. Portable files:
dir "backend\release\Contrack-Client-*-portable.exe" /b
goto END

:ERROR
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" set "EXIT_CODE=1"
echo Build portable failed.

:END
if "%PAUSE_ON_EXIT%"=="1" (
    echo.
    echo Press any key to exit...
    pause >nul
)
endlocal & exit /b %EXIT_CODE%
