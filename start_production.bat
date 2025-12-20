@echo off
REM Production startup script for Dental Chatbot (Windows)

echo ==========================================
echo Dental Chatbot - Production Startup
echo ==========================================

REM Load environment variables from .env if it exists
if exist .env (
    echo Loading environment variables from .env...
    for /f "tokens=*" %%a in (.env) do (
        set "%%a"
    )
    echo Environment variables loaded
) else (
    echo Warning: .env file not found. Using defaults.
)

REM Set environment to production
set ENV=production

REM Check Python
python --version
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.8+
    exit /b 1
)

REM Check if virtual environment exists
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat
echo Virtual environment activated

REM Install/update dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
echo Dependencies installed

REM Start Vision Server
echo Starting Vision API Server...
start "Vision Server" cmd /k "python run_vision_server.py --host %VISION_API_HOST% --port %VISION_API_PORT%"
echo Vision Server started
echo   Access at: http://localhost:%VISION_API_PORT%

REM Wait a moment
timeout /t 2 /nobreak >nul

REM Start Rasa Server (if needed)
if not "%START_RASA%"=="false" (
    echo Starting Rasa Server...
    cd rasa_bot\actions
    start "Rasa Server" cmd /k "rasa run --enable-api --port %RASA_PORT%"
    cd ..\..
    
    timeout /t 2 /nobreak >nul
    
    echo Starting Rasa Actions Server...
    cd rasa_bot\actions
    start "Rasa Actions" cmd /k "rasa run actions --port %RASA_ACTIONS_PORT%"
    cd ..\..
)

echo.
echo ==========================================
echo All services started!
echo ==========================================
echo Vision API: http://localhost:%VISION_API_PORT%
if not "%START_RASA%"=="false" (
    echo Rasa API: http://localhost:%RASA_PORT%
    echo Rasa Actions: http://localhost:%RASA_ACTIONS_PORT%
)
echo.
echo Services are running in separate windows.
echo Close those windows to stop the services.
echo ==========================================

pause

