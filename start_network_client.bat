@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if exist "AHO_Inventory.exe" (
    start "AHO Client" "AHO_Inventory.exe" --network-client
    goto done
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Build AHO_Inventory.exe first with build_windows.bat, or prepare .venv on this PC.
    pause
    goto done
)
start "AHO Client" ".venv\Scripts\pythonw.exe" "run_inventory.py" --network-client
:done
popd
endlocal
