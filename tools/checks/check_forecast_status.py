import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("检查数据库中的预测结果...")

try:
    # 连接数据库
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # 查询预测结果
    print("\n查询预测结果...")
    query = """
    SELECT spu, run_date, COUNT(*) as count
    FROM finedatalink.sales_forecast_history
    GROUP BY spu, run_date
    ORDER BY run_date DESC, spu
    """
    
    with engine.connect() as conn:
        result = pd.read_sql(text(query), con=conn)
    
    print(f"✓ 查询成功: {len(result)} 条记录")
    print("\nSPU预测记录（按日期分组）:")
    print(result)
    
    # 查询最近的预测记录
    print("\n查询最近的预测记录...")
    recent_query = """
    SELECT *
    FROM finedatalink.sales_forecast_history
    ORDER BY run_date DESC, spu, forecast_target_date
    LIMIT 20
    """
    
    with engine.connect() as conn:
        recent_result = pd.read_sql(text(recent_query), con=conn)
    
    print(f"✓ 查询成功: {len(recent_result)} 条记录")
    print("\n最近的预测记录:")
    print(recent_result[['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value']])
    
    engine.dispose()
    print("\n检查完成!")
    
except Exception as e:
    print(f"✗ 检查失败: {e}")
    import traceback
    traceback.print_exc()
