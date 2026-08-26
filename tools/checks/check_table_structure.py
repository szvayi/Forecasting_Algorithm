import os
import traceback
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 获取数据库连接URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print(f"数据库连接URL: {DB_URL}")
print(f"Python版本: {sys.version}")

# 检查依赖项
print("检查依赖项...")
try:
    import psycopg2
    print("psycopg2 已安装")
except ImportError:
    print("psycopg2 未安装")

try:
    # 连接数据库
    engine = create_engine(DB_URL)
    print("创建数据库引擎成功")
    
    # 检查表结构
    try:
        print("尝试连接数据库...")
        with engine.connect() as conn:
            print("数据库连接成功！")
            
            # 检查表是否存在
            check_table_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'finedatalink' 
                AND table_name = 'sales_forecast_history'
            )
            """)
            table_exists = conn.execute(check_table_query).scalar()
            
            print(f"表是否存在: {table_exists}")
            
            if not table_exists:
                print("表不存在！")
            else:
                # 查看表结构
                describe_query = text("""
                SELECT column_name, data_type, character_maximum_length 
                FROM information_schema.columns 
                WHERE table_schema = 'finedatalink' 
                AND table_name = 'sales_forecast_history'
                ORDER BY ordinal_position
                """)
                columns = conn.execute(describe_query).fetchall()
                
                print("表结构:")
                print("-" * 50)
                print(f"{'字段名':<25} {'数据类型':<20} {'长度':<10}")
                print("-" * 50)
                for col in columns:
                    print(f"{col[0]:<25} {col[1]:<20} {col[2] if col[2] else '-':<10}")
                
                # 查看表中的数据量
                count_query = text("""
                SELECT COUNT(*) FROM finedatalink.sales_forecast_history
                """)
                count = conn.execute(count_query).scalar()
                print(f"\n表中数据量: {count}")
                
                # 查看最近的几条数据
                sample_query = text("""
                SELECT * FROM finedatalink.sales_forecast_history
                ORDER BY run_date DESC
                LIMIT 3
                """)
                samples = conn.execute(sample_query).fetchall()
                print("\n最近3条数据:")
                for row in samples:
                    print(row)
    except Exception as e:
        print(f"数据库操作失败: {e}")
        traceback.print_exc()
    finally:
        engine.dispose()
        print("数据库连接已关闭")
except Exception as e:
    print(f"创建数据库引擎失败: {e}")
    traceback.print_exc()

print("脚本执行完毕")