@echo off
title LINE SME Bot - ngrok
cd /d "F:\AI\line-sme-bot"
echo ==========================================
echo  ngrok tunnel -> localhost:8001
echo ==========================================
echo.
echo After ngrok starts, copy the https URL and update:
echo   LINE Developers Console - Webhook URL
echo   .env - PUBLIC_BASE_URL
echo.
.\ngrok.exe http 8001
pause
