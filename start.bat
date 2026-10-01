@echo off
rem Starts the Fantasy King dashboard. Double-click this file.
rem To stop the app: click this window and press Ctrl+C, or just close the window.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The virtual environment is missing.
    echo Follow "First-time setup" in README.md, then run this file again.
    pause
    exit /b 1
)

echo Starting Fantasy King. Your browser will open in a few seconds.
echo To stop the app, press Ctrl+C in this window or close it.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
