@echo off
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
call setup_windows.bat
if errorlevel 1 exit /b 1
:install
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install --disable-pip-version-check PyInstaller==6.16.0
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name AHO_Inventory --collect-all uvicorn --collect-all fastapi --collect-all PySide6 --collect-all openpyxl --collect-all reportlab run_inventory.py
if errorlevel 1 exit /b 1
copy /y "start_local.bat" "dist\AHO_Inventory\start_local.bat" >nul
copy /y "QUICK_START_RU.md" "dist\AHO_Inventory\QUICK_START_RU.md" >nul
copy /y "network.json" "dist\AHO_Inventory\network.json" >nul
copy /y "start_network_server.bat" "dist\AHO_Inventory\start_network_server.bat" >nul
copy /y "start_network_client.bat" "dist\AHO_Inventory\start_network_client.bat" >nul
echo Build finished: dist\AHO_Inventory\AHO_Inventory.exe
echo Start this EXE to launch the local server and desktop client together.
echo Keep the complete dist\AHO_Inventory directory, including _internal.
echo Test on Windows before deployment. This build script was not tested on Windows here.
endlocal
