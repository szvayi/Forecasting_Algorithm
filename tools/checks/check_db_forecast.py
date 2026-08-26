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
    ORDER BY run_date DESC
    LIMIT 10
    """
    
    with engine.connect() as conn:
        result = pd.read_sql(text(query), con=conn)
    
    print(f"✓ 查询成功: {len(result)} 条记录")
    print("\n最近的预测记录:")
    print(result)
    
    # 查询SPU数量
    print("\n查询SPU数量...")
    spu_query = """
    SELECT DISTINCT spu
    FROM finedatalink.sales_forecast_history
    ORDER BY spu
    """
    
    with engine.connect() as conn:
        spu_result = pd.read_sql(text(spu_query), con=conn)
    
    print(f"✓ 查询成功: {len(spu_result)} 个SPU")
    print("\nSPU列表:")
    print(spu_result['spu'].tolist())
    
    engine.dispose()
    print("\n检查完成!")
    
except Exception as e:
    print(f"✗ 检查失败: {e}")
    import traceback
    traceback.print_exc()
