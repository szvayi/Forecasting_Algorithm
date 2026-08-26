@echo off
echo ========================================
echo 执行数据库写入
echo ========================================

cd /d C:\Users\VY0814\Forecasting_Algorithm

echo.
echo 1. 测试数据库连接...
python -c "import os; from sqlalchemy import create_engine, text; DB_URL = os.getenv('SALES_FORECAST_DB_URL', 'postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink'); engine = create_engine(DB_URL, pool_pre_ping=True); conn = engine.connect(); result = conn.execute(text('SELECT 1')); print('✅ 连接成功:', result.fetchone()); conn.close(); engine.dispose()"

echo.
echo 2. 检查当前数据...
python -c "import os; from sqlalchemy import create_engine, text; DB_URL = os.getenv('SALES_FORECAST_DB_URL', 'postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink'); engine = create_engine(DB_URL, pool_pre_ping=True); conn = engine.connect(); result = conn.execute(text('SELECT COUNT(*) FROM finedatalink.sales_forecast_history')); print('📊 数据记录数:', result.fetchone()[0]); conn.close(); engine.dispose()"

echo.
echo 3. 读取CSV文件...
python -c "import pandas as pd; df = pd.read_csv('D:/华熠/output/spu_forecast_2026-03-10.csv'); print('✅ CSV读取成功:', len(df), '行')"

echo.
echo 4. 执行数据库写入...
python write_db_full.py

echo.
echo ========================================
echo ✅ 完成!
echo ========================================

pause
