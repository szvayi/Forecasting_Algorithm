@echo off
setlocal

:: --- Configuration ---
set PROJ_DIR=C:\Users\VY0814\Forecasting_Algorithm
set VENV_PYTHON=%PROJ_DIR%\.venv\Scripts\python.exe
set DB_URL=postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink
set SPU_LIST=0887,0779,0849,0855
set PYTHONIOENCODING=utf-8

cd /d %PROJ_DIR%

echo [INFO] Starting Forecast Pipeline at %DATE% %TIME%

:: 1. Run Main Forecast
echo [INFO] Running main forecasting engine...
set SALES_FORECAST_DB_URL=%DB_URL%
set SPU_LIST=%SPU_LIST%
%VENV_PYTHON% main.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] main.py failed with exit code %ERRORLEVEL%
    goto :Error
)

:: 2. Generate Reports
echo [INFO] Generating reports...
%VENV_PYTHON% generate_accuracy_report.py --run-date %DATE:~0,4%-%DATE:~5,2%-%DATE:~8,2%
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Report generation failed.
)

:: 3. Run Monitor/Alert
echo [INFO] Running monitor and alert check...
%VENV_PYTHON% scripts/monitor_alert.py
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Alert triggered or monitor failed.
)

echo [SUCCESS] Pipeline completed successfully.
exit /b 0

:Error
echo [FAIL] Pipeline failed. Check logs in %PROJ_DIR%\logs
exit /b 1
