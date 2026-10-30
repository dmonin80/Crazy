@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if exist "AHO_Inventory.exe" (
    start "AHO Local" "AHO_Inventory.exe" --local
    exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" goto setup
.venv\Scripts\python.exe check_dependencies.py >nul 2>&1
if not errorlevel 1 goto launch
:setup
call setup_windows.bat
if errorlevel 1 (
    pause
    exit /b 1
)
:launch
start "AHO Local" ".venv\Scripts\pythonw.exe" "run_inventory.py" --local
popd
endlocal
