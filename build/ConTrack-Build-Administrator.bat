@echo off

:START
set /p branch=Set Branch:

IF /I "%branch%" == "" GOTO START

set version=%branch%
set build_dir=C:\Contrack\build-tool\build
set project_root_dir=C:\Contrack\build-tool
set project_dir=%project_root_dir%\source

set source_server_dir=%project_dir%\src-server\build\*.war
set target_server_dir=%build_dir%\ConTrack_API_%version%.zip
set source_client_dir=%project_dir%\src\w-SCMS\bin\x64\Debug\*
set target_client_dir=%build_dir%\ConTrack_Client_%version%.zip

echo Pull latest Contrack source!

dir "%project_dir%" /a /b | findstr . >nul
if errorlevel 1 (
    mkdir %project_root_dir%
	cd /d %project_root_dir%
	git clone https://github.com/Veriserve/ConTrack.git	
	
	echo Clone new source success!
)

if not exist "%project_dir%\src\CCM.ClientManage\packages\BouncyCastle.1.8.9" (
	cd /d "%~dp0"
	"nuget.exe" restore "%project_dir%\src\w-SCMS.sln"
	
    cd /d "%~dp0"
	"nuget.exe" restore "%project_dir%\src\CCM.ClientManage\CCM.ClientManage.csproj" -PackagesDirectory "%project_dir%\src\CCM.ClientManage\packages"
)
	
cd /d %project_dir%

git stash
::set "GIT_STASH=git stash"
::powershell -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/k %GIT_STASH%'"

git fetch
::set "GIT_FETCH=git fetch"
::powershell -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/k %GIT_FETCH%'"

git branch -D %branch%
::set "GIT_BRANCH_DEL=git branch -D %branch%"
::powershell -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/k %GIT_BRANCH_DEL%'"

git checkout %branch%
::set "GIT_BRANCH_CHECKOUT=git checkout %branch%"
::powershell -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/k %GIT_BRANCH_CHECKOUT%'"

git pull
::set "GIT_PULL=git pull"
::powershell -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/k %GIT_PULL%'"

git stash pop
::set "GIT_STASH_POP=git stash pop"
::powershell -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/k %GIT_STASH_POP%'"

git checkout origin/%branch% src\w-SCMS.DocumentParser\w-SCMS.DocumentParser.csproj

::cd %project_dir%\src-server

::run ConTrack Server with administrator privileges
::start "Build ConTrack API" cmd /k "call packageObfuscate.bat"

echo Option:
echo 1. Build both CLIENT and API
echo 2. Build only API
echo 3. Build only CLIENT
set /p confirm="Please select option (1/2/3):"

IF /I "%confirm%" EQU "2" GOTO SERVER

IF /I "%confirm%" EQU "3" GOTO CLIENT

:CLIENT
cd /d %project_dir%\src\w-SCMS.DocumentParser

powershell -Command "(Get-Content w-SCMS.DocumentParser.csproj) -replace '<PreBuildEvent>','<!--<PreBuildEvent>' | Set-Content w-SCMS.DocumentParser.csproj"
powershell -Command "(Get-Content w-SCMS.DocumentParser.csproj) -replace '<\/PreBuildEvent>','<\/PreBuildEvent>-->' | Set-Content w-SCMS.DocumentParser.csproj"

echo Remove event document parser!

cd /d "%~dp0"

xcopy "Interop.MLApp.dll" "%project_dir%\src\3rdParty\MATLAB\" /Y

echo Copy MLApp.dll!

cd /d "%~dp0"

xcopy "CCM.ClientManage.csproj" "%project_dir%\src\CCM.ClientManage\" /Y

echo Copy CCM.ClientManage config!

echo Start build Contrack Client!

cd /d %project_dir%\src\CCM.ClientManage

"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" CCM.ClientManage.csproj /t:Clean /p:Configuration=Debug /p:Platform=x64
"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" CCM.ClientManage.csproj /t:ReBuild /p:Configuration=Debug /p:Platform=x64

cd /d %project_dir%\src\w-SCMS

::run ConTrack Client with administrator privileges

"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" w-SCMS.csproj /t:Clean /p:Configuration=Debug /p:Platform=x64
"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" w-SCMS.csproj /t:ReBuild /p:Configuration=Debug /p:Platform=x64

::"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" w-SCMS.csproj /t:Clean /p:Configuration=ConTrackClientInstaller-Obfucar /p:Platform=x64
"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\Common7\IDE\devenv.com" w-SCMS.sln /Clean "ConTrackClientInstaller-Obfucar|x64" /Project "ConTrackClientInstaller-Obfucar-x64"
"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\Common7\IDE\devenv.com" w-SCMS.sln /Rebuild "ConTrackClientInstaller-Obfucar|x64" /Project "ConTrackClientInstaller-Obfucar-x64"

echo Remove authentication config file...

del /F "%project_dir%\src\w-SCMS\bin\x64\Debug\recent.xml"
del /F "%project_dir%\src\w-SCMS\bin\x64\Debug\session.xml"
del /F "%project_dir%\src\w-SCMS\bin\x64\Debug\repository_auth.xml"
del /F "%project_dir%\src\w-SCMS\bin\x64\Debug\repositoryGit_auth.xml"
del /F "%project_dir%\src\w-SCMS\bin\x64\Debug\repositoryGitlab_auth.xml"
del /F "%project_dir%\src\w-SCMS\bin\x64\Debug\repositoryBitbucket_auth.xml"

echo Remove authentication config file done!

echo Copy network file...

cd /d "%~dp0"

xcopy "network.xml" "%project_dir%\src\w-SCMS\bin\x64\Debug\" /Y

echo Copy network file done!

echo Zipping Client file to %build_dir%...

if not exist "%build_dir%" (
	mkdir %build_dir%
)

powershell Compress-Archive -Path "%source_client_dir%" -DestinationPath "%target_client_dir%" -Force

echo Zip Client file success!

IF /I "%confirm%" EQU "3" GOTO END

:SERVER
echo Start build Contrack Server!

powershell -Command "Start-Process '%project_dir%\src-server\packageObfuscate.bat' -Verb RunAs"

set /p buildAPI="Please wait build API completed. Do you zip API file? (y/n):"

echo Zipping Server file to %build_dir%...

powershell Compress-Archive -Path "%source_server_dir%" -DestinationPath "%target_server_dir%" -Force

echo Zip Server file success!

:END

echo Please check zip file on %build_dir%!

set /p rebuild="Do you need rebuild? (y/n):"

IF /I "%rebuild%" == "y" GOTO START

pause