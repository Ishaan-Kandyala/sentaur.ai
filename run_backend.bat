@echo off
echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Starting backend server...
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

pause
