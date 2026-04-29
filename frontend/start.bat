@echo off
echo Starting Event ROI Dashboard Frontend...
cd /d "%~dp0"
if not exist "node_modules" (
    echo Installing dependencies...
    npm install
)
echo Frontend running at http://localhost:5173
npm run dev
