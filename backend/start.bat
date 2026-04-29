@echo off
echo Starting Event ROI Dashboard Backend...
cd /d "%~dp0"
if not exist ".env" (
    echo Copying .env.example to .env ...
    copy .env.example .env
    echo Please edit .env and add your GEMINI_API_KEY, then re-run this script.
    pause
    exit /b 1
)
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)
echo Backend running at http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
