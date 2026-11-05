import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL")
if not DB_URL:
    raise RuntimeError("缺少环境变量 SALES_FORECAST_DB_URL，参见 ENV.md")

engine = create_engine(DB_URL, pool_pre_ping=True)

try:
    # 查看数据库中的所有表
    query = """
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_schema IN ('public', 'finedatalink') 
    ORDER BY table_schema, table_name
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"数据库中的所有表:")
    print(df.to_string())
    
    engine.dispose()
    
except Exception as e:
    print(f"查询失败: {e}")
    import traceback
    traceback.print_exc()
    engine.dispose()