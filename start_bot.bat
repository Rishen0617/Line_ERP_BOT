@echo off
title LINE SME Bot - uvicorn
cd /d "F:\AI\line-sme-bot"
echo ==========================================
echo  LINE SME Bot - Starting on port 8001
echo ==========================================
echo.
echo Health check after start:
echo   http://localhost:8001/health
echo   http://localhost:8001/dashboard
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
pause
