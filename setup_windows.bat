@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if exist ".venv\Scripts\python.exe" goto dependencies
py -3.12 -m venv .venv
if not errorlevel 1 goto dependencies
py -3.14 -m venv .venv
if errorlevel 1 goto failed
:dependencies
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe check_dependencies.py
if errorlevel 1 goto failed
echo Setup complete. Use start_local.bat for a local database.
popd
exit /b 0
:failed
echo Setup failed. Install 64-bit Python 3.12 or 3.14 and review the errors above.
popd
exit /b 1
