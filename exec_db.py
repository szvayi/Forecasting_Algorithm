"""
直接执行数据库写入
"""

import os
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("数据库URL:", DB_URL)

engine = create_engine(DB_URL, pool_pre_ping=True)

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("连接成功:", result.fetchone())
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
        count = result.fetchone()[0]
        print("数据记录数:", count)
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM finedatalink.sales_forecast_history LIMIT 3"))
        rows = result.fetchall()
        print("最新数据:")
        for row in rows:
            print(row)
    
finally:
    engine.dispose()
