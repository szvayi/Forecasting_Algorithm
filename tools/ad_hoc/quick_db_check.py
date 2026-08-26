import sys
sys.path.insert(0, '.')

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

try:
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # 检查预测结果表
    query = "SELECT COUNT(*) as count FROM spu_forecast_results"
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    count = df['count'].iloc[0]
    print(f"数据库中的预测结果数量: {count}")
    
    if count > 0:
        # 查看最新的预测结果
        query = """
        SELECT spu, run_date, forecast_target_date, spu_forecast_value, winner_algo, validation_wmape
        FROM spu_forecast_results
        ORDER BY run_date DESC, spu, forecast_target_date
        LIMIT 20
        """
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        
        print("\n最新的预测结果:")
        print(df.to_string())
        
        # 查看有多少个不同的SPU
        query = "SELECT COUNT(DISTINCT spu) as spu_count FROM spu_forecast_results"
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        
        print(f"\n不同的SPU数量: {df['spu_count'].iloc[0]}")
    
    engine.dispose()
    
except Exception as e:
    print(f"查询失败: {e}")
    import traceback
    traceback.print_exc()