@echo off
REM ===================================================================
REM  penny_radar - 미국 동전주 화제성 스캔 후 텔레그램 발송
REM  더블클릭하면 바로 실행됩니다.
REM  발송 없이 확인만: run_radar.bat --dry
REM ===================================================================
chcp 65001 >nul
cd /d "%~dp0"

"C:\trading_ai\venv\Scripts\python.exe" penny_radar.py %*

echo.
echo ---------------------------------------------------------------
echo Done. CSV saved in the  reports\  folder.
echo Press any key to close this window.
pause >nul
