@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "PAUSE_ON_EXIT=1"
if /i "%~1"=="--no-pause" set "PAUSE_ON_EXIT=0"
if /i "%~2"=="--no-pause" set "PAUSE_ON_EXIT=0"
if /i "%~3"=="--no-pause" set "PAUSE_ON_EXIT=0"

if /i "%~1"=="help" goto usage
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage

set "VERSION_ARG=%~1"
set "DEPLOY_CHOICE=%~2"
if /i "%VERSION_ARG%"=="--no-pause" set "VERSION_ARG="
if /i "%DEPLOY_CHOICE%"=="--no-pause" set "DEPLOY_CHOICE="

if "%VERSION_ARG%"=="" (
  echo.
  echo Enter new version or bump type.
  echo Examples: patch, minor, major, 0.2.0
  set /p "VERSION_ARG=Version [patch]: "
  if "!VERSION_ARG!"=="" set "VERSION_ARG=patch"
)

echo.
echo Contrack local server release
echo =============================
echo Version argument: %VERSION_ARG%
echo.

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found in PATH.
  goto failed
)

echo Updating package version...
call npm version %VERSION_ARG% --no-git-tag-version
if errorlevel 1 goto failed

for /f "usebackq delims=" %%v in (`node -p "require('./package.json').version"`) do set "NEW_VERSION=%%v"
if "%NEW_VERSION%"=="" (
  echo ERROR: Could not read package.json version.
  goto failed
)

echo.
echo Building web and local server release for version %NEW_VERSION%...
call npm run build
if errorlevel 1 goto failed

echo.
echo Release artifacts created:
echo   build_output\web
echo   build_output\local-server
echo   build_output\releases\local-server\latest.json
echo   build_output\releases\local-server\contrack-local-server-%NEW_VERSION%.bundle.json.gz
echo.

if /i "%DEPLOY_CHOICE%"=="--deploy" goto deploy
if /i "%DEPLOY_CHOICE%"=="deploy" goto deploy
if /i "%DEPLOY_CHOICE%"=="--no-deploy" goto done
if /i "%DEPLOY_CHOICE%"=="no-deploy" goto done

set /p "ANSWER=Deploy Docker now with docker compose up --build -d? [y/N]: "
if /i "%ANSWER%"=="y" goto deploy
if /i "%ANSWER%"=="yes" goto deploy
goto done

:deploy
where docker >nul 2>nul
if errorlevel 1 (
  echo ERROR: docker was not found in PATH.
  goto failed
)
echo.
echo Deploying Docker services...
docker compose up --build -d
if errorlevel 1 goto failed

:done
echo.
echo Done. Current release version: %NEW_VERSION%
goto success

:usage
echo Usage:
echo   create-version.bat patch [--deploy^|--no-deploy]
echo   create-version.bat minor [--deploy^|--no-deploy]
echo   create-version.bat major [--deploy^|--no-deploy]
echo   create-version.bat 0.1.1 [--deploy^|--no-deploy]
echo.
echo Examples:
echo   create-version.bat patch
echo   create-version.bat 0.2.0 --deploy
goto success

:failed
echo.
echo ERROR: Release creation failed.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 1

:success
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 0
