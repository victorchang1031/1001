@echo off
cd /d "c:\Users\victo\Documents\Practice.py"
"C:\Users\victo\AppData\Local\Programs\Python\Python310\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
