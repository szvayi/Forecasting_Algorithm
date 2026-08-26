import sys
sys.path.insert(0, '.')

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

print("检查数据库中的预测结果...")

try:
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # 检查预测结果表
    query = """
    SELECT 
        spu,
        COUNT(*) as forecast_count,
        MIN(forecast_target_date) as min_date,
        MAX(forecast_target_date) as max_date,
        AVG(spu_forecast_value) as avg_forecast,
        MAX(run_date) as latest_run_date
    FROM spu_forecast_results
    GROUP BY spu
    ORDER BY spu
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"\n找到 {len(df)} 个SPU的预测结果:")
    print(df.to_string())
    
    # 检查总记录数
    count_query = "SELECT COUNT(*) as total_count FROM spu_forecast_results"
    with engine.connect() as conn:
        count_df = pd.read_sql(text(count_query), con=conn)
    
    print(f"\n总预测记录数: {count_df['total_count'].iloc[0]}")
    
    # 检查最新的运行日期
    latest_query = "SELECT MAX(run_date) as latest_run FROM spu_forecast_results"
    with engine.connect() as conn:
        latest_df = pd.read_sql(text(latest_query), con=conn)
    
    print(f"最新运行日期: {latest_df['latest'].iloc[0]}")
    
    engine.dispose()
    print("\n检查完成!")
    
except Exception as e:
    print(f"检查失败: {e}")
    import traceback
    traceback.print_exc()