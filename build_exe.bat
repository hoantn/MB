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

REM --- B5.1: opencv GUI de loi DLL trong PyInstaller; dung headless cho xu ly anh ---
REM Go ca metadata/cu muc cv2 bi hong de pip khong nham la da cai du.
pip uninstall -y opencv-python opencv-contrib-python opencv-contrib-python-headless opencv-python-headless >nul 2>nul

REM --- B6: cài dependency ---
if exist requirements.txt (
    echo [INFO] Installing requirements...
    pip install -r requirements.txt
) else (
    echo [WARN] requirements.txt not found, skipping.
)

REM --- B6.0: dam bao cv2 thuc su ton tai sau khi go ban GUI ---
pip install --force-reinstall --no-cache-dir opencv-python-headless
if errorlevel 1 (
    echo [ERROR] Cannot install opencv-python-headless.
    pause
    exit /b 1
)

REM --- B6.1: fail fast nếu Qt binding không có trong đúng venv build ---
python -c "import PySide6, shiboken6; print('[INFO] PySide6 OK:', PySide6.__file__)"
if errorlevel 1 (
    echo [ERROR] PySide6 is missing in build venv. Check requirements.txt/install log.
    pause
    exit /b 1
)

REM --- B6.2: fail fast neu OpenCV/cv2 khong co trong dung venv build ---
python -c "import cv2; print('[INFO] cv2 OK:', cv2.__version__, cv2.__file__)"
if errorlevel 1 (
    echo [ERROR] cv2 is missing in build venv. Install opencv-python-headless.
    pause
    exit /b 1
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
copy /Y config\config*.json dist\MBTool\config\ >nul

REM --- copy toàn bộ config/games/* ---
if not exist dist\MBTool\config\games (
    mkdir dist\MBTool\config\games
)
xcopy /E /I /Y config\games dist\MBTool\config\games >nul

copy /Y icon.ico dist\MBTool\icon.ico >nul

REM --- copy chrome extensions theo Tool ---
if not exist dist\MBTool\chrome_ext (
    mkdir dist\MBTool\chrome_ext
)
xcopy /E /I /Y chrome_ext dist\MBTool\chrome_ext >nul

REM --- B11: kiểm tra kết quả ---
if exist dist\MBTool\MBTool.exe (
    if not exist dist\MBTool\_internal\PySide6 (
        echo [ERROR] BUILD INVALID: dist\MBTool\_internal\PySide6 is missing.
        pause
        exit /b 1
    )
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
