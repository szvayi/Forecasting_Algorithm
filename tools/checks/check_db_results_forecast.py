import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

output_file = "db_check_results.txt"

with open(output_file, 'w', encoding='utf-8') as f:
    try:
        engine = create_engine(DB_URL, pool_pre_ping=True)
        
        # 检查预测结果表
        query = "SELECT COUNT(*) as count FROM finedatalink.sales_forecast_history"
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        
        count = df['count'].iloc[0]
        f.write(f"数据库中的预测结果数量: {count}\n\n")
        
        if count > 0:
            # 查看最新的预测结果
            query = """
            SELECT spu, run_date, forecast_target_date, spu_forecast_value, winner_algo, validation_wmape
            FROM finedatalink.sales_forecast_history
            ORDER BY run_date DESC, spu, forecast_target_date
            LIMIT 20
            """
            
            with engine.connect() as conn:
                df = pd.read_sql(text(query), con=conn)
            
            f.write("最新的预测结果:\n")
            f.write(df.to_string())
            f.write("\n\n")
            
            # 查看有多少个不同的SPU
            query = "SELECT COUNT(DISTINCT spu) as spu_count FROM finedatalink.sales_forecast_history"
            with engine.connect() as conn:
                df = pd.read_sql(text(query), con=conn)
            
            f.write(f"不同的SPU数量: {df['spu_count'].iloc[0]}\n")
        
        engine.dispose()
        
    except Exception as e:
        f.write(f"查询失败: {e}\n")
        import traceback
        traceback.print_exc(file=f)
        engine.dispose()

print("查询完成，结果已保存到:", output_file)