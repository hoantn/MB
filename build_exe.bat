@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ==========================================
echo  MB TOOL - COMMERCIAL BUILD (ONEDIR)
echo ==========================================

REM --- B1: đảm bảo đang ở thư mục project ---
cd /d %~dp0

REM --- B2: kiểm tra Python ---
python --version
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

REM --- B3: tạo venv nếu chưa có ---
if not exist venv (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

REM --- B4: kích hoạt venv ---
call venv\Scripts\activate

REM --- B5: upgrade pip ---
python -m pip install --upgrade pip

REM --- B6: cài dependency ---
if exist requirements.txt (
    echo [INFO] Installing requirements...
    pip install -r requirements.txt
) else (
    echo [WARN] requirements.txt not found, skipping.
)

REM --- B7: cài PyInstaller ---
pip install --upgrade pyinstaller pyinstaller-hooks-contrib

REM --- B8: xoá build cũ ---
if exist build (
    echo [INFO] Removing old build folder...
    rmdir /s /q build
)

if exist dist (
    echo [INFO] Removing old dist folder...
    rmdir /s /q dist
)

REM --- B9: build bằng spec (bắt buộc dùng python -m để không lệch venv) ---
echo [INFO] Building MBTool (onedir)...
python -m PyInstaller build.spec --clean
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

REM --- B10: POST-COPY ASSETS (CHỐT HẠ) ---
REM Yêu cầu chuẩn:
REM   dist\MBTool\vision\opp\...
REM   dist\MBTool\config\config.json
REM   dist\MBTool\icon.ico
echo [INFO] Ensuring assets in dist\MBTool\...

if not exist dist\MBTool\vision\opp (
    mkdir dist\MBTool\vision\opp
)
xcopy /E /I /Y vision\opp dist\MBTool\vision\opp >nul

if not exist dist\MBTool\config (
    mkdir dist\MBTool\config
)
copy /Y config\config.json dist\MBTool\config\config.json >nul

REM --- copy toàn bộ config/games/* ---
if not exist dist\MBTool\config\games (
    mkdir dist\MBTool\config\games
)
xcopy /E /I /Y config\games dist\MBTool\config\games >nul

copy /Y icon.ico dist\MBTool\icon.ico >nul

REM --- B11: kiểm tra kết quả ---
if exist dist\MBTool\MBTool.exe (
    echo.
    echo ==========================================
    echo  BUILD SUCCESS!
    echo  Output: dist\MBTool\
    echo ==========================================
    echo  Check:
    echo    - dist\MBTool\vision\opp\
    echo    - dist\MBTool\config\config.json
    echo    - dist\MBTool\icon.ico
) else (
    echo.
    echo ==========================================
    echo  BUILD FAILED!
    echo ==========================================
)

pause
