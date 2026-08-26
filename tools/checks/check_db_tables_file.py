import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

output_file = "db_tables.txt"

with open(output_file, 'w', encoding='utf-8') as f:
    try:
        engine = create_engine(DB_URL, pool_pre_ping=True)
        
        # 查看数据库中的所有表
        query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name
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