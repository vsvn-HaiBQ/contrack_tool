@echo off
setlocal

cd /d "%~dp0"
set "EXIT_CODE=0"
set "PAUSE_ON_EXIT=0"
if /I "%~1"=="pause" set "PAUSE_ON_EXIT=1"

echo Install frontend dependencies with pnpm...
cd frontend
call corepack pnpm install
if errorlevel 1 goto ERROR

echo Build web frontend...
call corepack pnpm build
if errorlevel 1 goto ERROR

cd ..
if not exist "build_output\web" mkdir "build_output\web"

echo Copy web dist to build_output\web...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Copy-Item -Path 'frontend\dist\*' -Destination 'build_output\web' -Recurse -Force"
if errorlevel 1 goto ERROR

echo Build local Node server package...
node local-server\scripts\build.cjs
if errorlevel 1 goto ERROR

echo Done.
echo Web files: build_output\web
echo Local Node server: build_output\local-server\start-local-server.bat
goto END

:ERROR
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" set "EXIT_CODE=1"
echo Build web/local-server failed.

:END
if "%PAUSE_ON_EXIT%"=="1" (
    echo.
    echo Press any key to exit...
    pause >nul
)
endlocal & exit /b %EXIT_CODE%
