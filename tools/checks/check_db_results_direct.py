import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL")
if not DB_URL:
    raise RuntimeError("缺少环境变量 SALES_FORECAST_DB_URL，参见 ENV.md")

engine = create_engine(DB_URL, pool_pre_ping=True)

try:
    # 检查预测结果表
    query = "SELECT * FROM spu_forecast_results LIMIT 10"
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"找到 {len(df)} 条预测结果:")
    print(df.to_string())
    
    # 检查总记录数
    count_query = "SELECT COUNT(*) as total_count FROM spu_forecast_results"
    with engine.connect() as conn:
        count_df = pd.read_sql(text(count_query), con=conn)
    
    print(f"\n总预测记录数: {count_df['total_count'].iloc[0]}")
    
    engine.dispose()
    
except Exception as e:
    print(f"检查失败: {e}")
    import traceback
    traceback.print_exc()
    engine.dispose()