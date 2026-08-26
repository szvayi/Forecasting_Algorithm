import sys
sys.path.insert(0, '.')

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

output_file = "db_check_results.txt"

with open(output_file, 'w', encoding='utf-8') as f:
    f.write("检查数据库中的预测结果...\n\n")
    
    try:
        engine = create_engine(DB_URL, pool_pre_ping=True)
        
        # 检查预测结果表
        query = "SELECT * FROM spu_forecast_results LIMIT 10"
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        
        f.write(f"找到 {len(df)} 条预测结果:\n")
        f.write(df.to_string())
        f.write("\n\n")
        
        # 检查总记录数
        count_query = "SELECT COUNT(*) as total_count FROM spu_forecast_results"
        with engine.connect() as conn:
            count_df = pd.read_sql(text(count_query), con=conn)
        
        f.write(f"总预测记录数: {count_df['total_count'].iloc[0]}\n")
        
        engine.dispose()
        
        f.write("\n检查完成!\n")
        
    except Exception as e:
        f.write(f"检查失败: {e}\n")
        import traceback
        traceback.print_exc(file=f)
        engine.dispose()

print("检查完成，结果已保存到:", output_file)