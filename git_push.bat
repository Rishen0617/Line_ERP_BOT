@echo off
cd /d "F:\AI\line-sme-bot"

echo === Git Status ===
git status

echo.
echo === Staging all changes ===
git add -A

echo.
echo === Commit ===
set /p msg="Commit message (or press Enter for default): "
if "%msg%"=="" set msg=[update] auto commit from Claude agent

git commit -m "%msg%"

echo.
echo === Pushing to GitHub ===
git push origin main

echo.
if %ERRORLEVEL%==0 (
    echo SUCCESS: Pushed to https://github.com/Rishen0617/Line_ERP_BOT
) else (
    echo ERROR: Push failed. Check git credentials or branch name.
)
echo.
pause
