@echo off
cd /d "c:\Users\victo\Documents\Practice.py"
python -m uvicorn app.main:app --port 8000
