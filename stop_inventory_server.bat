@echo off
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
.venv\Scripts\python.exe run_inventory.py --stop-server
if errorlevel 1 pause
exit /b
:missing
echo Start start_inventory.bat first to prepare the Python environment.
pause
exit /b 1
