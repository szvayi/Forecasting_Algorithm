import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

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