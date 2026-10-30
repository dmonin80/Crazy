@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if exist "AHO_Inventory.exe" (
    start "AHO Server" "AHO_Inventory.exe" --lan-host
    goto done
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Build AHO_Inventory.exe first with build_windows.bat, or prepare .venv on this PC.
    pause
    goto done
)
start "AHO Server" ".venv\Scripts\pythonw.exe" "run_inventory.py" --lan-host
:done
popd
endlocal
