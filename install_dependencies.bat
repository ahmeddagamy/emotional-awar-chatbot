@echo off
REM Installation script for Dental Chatbot Vision System (Windows)

echo ========================================
echo Installing Dependencies
echo ========================================
echo.

python -m pip install --upgrade pip

echo.
echo Installing core dependencies...
python -m pip install -r requirements.txt

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo To verify installation, run:
echo   python setup_and_test.py
echo.
echo To start the vision server, run:
echo   python run_vision_server.py
echo.
pause

