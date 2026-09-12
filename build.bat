@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Builds both artefacts, in the order they depend on each other:
REM
REM   installer\MaestroLauncher.ico   from the launcher's own logo
REM   launcher\MaestroLauncher.exe    PyInstaller, one file
REM   launcher\MaestroLauncherSetup.exe   Inno Setup, wrapping that exe
REM
REM The installer embeds the exe, so building it against a stale exe is the
REM one mistake worth making impossible -- hence one command for both.

echo === 1/3  icon
python installer\make_icon.py || goto :failed

echo.
echo === 2/3  exe
python -m PyInstaller MaestroLauncher.spec --noconfirm --clean || goto :failed
if not exist "launcher\MaestroLauncher.exe" (
    echo PyInstaller reported success but launcher\MaestroLauncher.exe is not there.
    goto :failed
)

echo.
echo === 3/3  installer

REM The version lives in core\__init__.py and nowhere else, so it is read from
REM there rather than written down a second time in the .iss. Via a script
REM rather than python -c: the quoting a regex needs does not survive cmd.
for /f "usebackq delims=" %%v in (`python installer\app_version.py`) do set APPVERSION=%%v
if "!APPVERSION!"=="" (
    echo Could not read __version__ out of core\__init__.py.
    goto :failed
)
echo version !APPVERSION!

REM Inno Setup installs per-user by default, so look there first, then the
REM machine-wide locations, then PATH.
set "ISCC="
for %%p in (
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if exist %%p set "ISCC=%%~p"
if not defined ISCC for %%p in (ISCC.exe) do if not "%%~$PATH:p"=="" set "ISCC=%%~$PATH:p"
if not defined ISCC (
    echo Inno Setup not found. Install it with:  winget install JRSoftware.InnoSetup
    goto :failed
)

"!ISCC!" /DAppVersion=!APPVERSION! MaestroLauncher.iss || goto :failed

echo.
echo === done
echo   launcher\MaestroLauncher.exe
echo   launcher\MaestroLauncherSetup.exe
exit /b 0

:failed
echo.
echo BUILD FAILED
exit /b 1
