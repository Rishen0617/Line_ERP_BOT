@echo off
cd /d "F:\AI\line-sme-bot"
echo === Staging all changes ===
git add -A
echo.
echo === Committing ===
git commit -m "feat: xlsx local-first dual-write architecture + openpyxl + utility scripts + manual updates"
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
