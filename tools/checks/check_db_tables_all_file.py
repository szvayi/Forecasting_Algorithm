import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL")
if not DB_URL:
    raise RuntimeError("缺少环境变量 SALES_FORECAST_DB_URL，参见 ENV.md")

output_file = "db_tables_all.txt"

with open(output_file, 'w', encoding='utf-8') as f:
    try:
        engine = create_engine(DB_URL, pool_pre_ping=True)
        
        # 查看数据库中的所有表
        query = """
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_schema IN ('public', 'finedatalink') 
        ORDER BY table_schema, table_name
        """
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        
        f.write(f"数据库中的所有表:\n")
        f.write(df.to_string())
        
        engine.dispose()
        
    except Exception as e:
        f.write(f"查询失败: {e}\n")
        import traceback
        traceback.print_exc(file=f)
        engine.dispose()

print("查询完成，结果已保存到:", output_file)