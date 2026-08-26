from sqlalchemy import create_engine, text
import datetime

# 数据库连接URL
DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

def check_db_data():
    try:
        # 连接数据库
        engine = create_engine(DB_URL, pool_pre_ping=True)
        
        # 执行查询
        with engine.connect() as conn:
            # 检查表是否存在
            table_exists_query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE  table_schema = 'finedatalink' 
                    AND    table_name   = 'sales_forecast_history'
                )
            """)
            table_exists = conn.execute(table_exists_query).scalar()
            
            # 检查数据量
            if table_exists:
                count_query = text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history")
                count = conn.execute(count_query).scalar()
                
                # 获取最近的几条数据
                recent_query = text("SELECT * FROM finedatalink.sales_forecast_history ORDER BY run_date DESC LIMIT 10")
                recent_data = conn.execute(recent_query).fetchall()
            else:
                count = 0
                recent_data = []
        
        # 关闭连接
        engine.dispose()
        
        # 写入结果到文件
        with open('db_check_result.txt', 'w', encoding='utf-8') as f:
            f.write(f"检查时间: {datetime.datetime.now()}\n")
            f.write(f"表是否存在: {table_exists}\n")
            f.write(f"数据条数: {count}\n")
            f.write("最近10条数据:\n")
            for row in recent_data:
                f.write(f"{row}\n")
        
        print("数据库检查完成，结果已写入 db_check_result.txt")
        
    except Exception as e:
        # 写入错误信息到文件
        with open('db_check_error.txt', 'w', encoding='utf-8') as f:
            f.write(f"检查时间: {datetime.datetime.now()}\n")
            f.write(f"错误信息: {str(e)}\n")
        
        print("数据库检查失败，错误信息已写入 db_check_error.txt")

if __name__ == "__main__":
    check_db_data()