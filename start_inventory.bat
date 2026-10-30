@echo off
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_deps
py -3.14 -m venv .venv
if errorlevel 1 goto python_error
:check_deps
.venv\Scripts\python.exe check_dependencies.py >nul 2>&1
if not errorlevel 1 goto launch
echo Installing application dependencies. Internet is needed for the first setup.
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto dependency_error
.venv\Scripts\python.exe check_dependencies.py
if errorlevel 1 goto dependency_error
:launch
start "AHO Inventory" ".venv\Scripts\pythonw.exe" "%~dp0run_inventory.py"
exit /b 0
:python_error
echo Python 3.14 was not found or the environment could not be created.
echo Install Python 3.14 for the source version, or use the compiled AHO_Inventory.exe.
pause
exit /b 1
:dependency_error
echo Could not install or load the dependencies. Review the error above.
pause
exit /b 1
