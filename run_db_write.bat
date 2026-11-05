@echo off
echo ========================================
echo 执行数据库写入
echo ========================================

cd /d C:\Users\VY0814\Forecasting_Algorithm

if not defined SALES_FORECAST_DB_URL (
  echo [ERROR] 请先设置环境变量 SALES_FORECAST_DB_URL，参见 ENV.md
  exit /b 1
)

echo.
echo 1. 测试数据库连接...
python -c "import os; from sqlalchemy import create_engine, text; DB_URL = os.environ['SALES_FORECAST_DB_URL']; engine = create_engine(DB_URL, pool_pre_ping=True); conn = engine.connect(); result = conn.execute(text('SELECT 1')); print('OK', result.fetchone()); conn.close(); engine.dispose()"

echo.
echo 2. 检查当前数据...
python -c "import os; from sqlalchemy import create_engine, text; DB_URL = os.environ['SALES_FORECAST_DB_URL']; engine = create_engine(DB_URL, pool_pre_ping=True); conn = engine.connect(); result = conn.execute(text('SELECT COUNT(*) FROM finedatalink.sales_forecast_history')); print('Count', result.fetchone()[0]); conn.close(); engine.dispose()"

echo.
echo 3. 读取CSV文件...
python -c "import pandas as pd; df = pd.read_csv('D:/华熠/output/spu_forecast_2026-03-10.csv'); print('CSV OK', len(df), 'rows')"

echo.
echo Done. Prefer: python write_db.py  (with SALES_FORECAST_DB_URL set)
