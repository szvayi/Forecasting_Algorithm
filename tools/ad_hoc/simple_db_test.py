"""
最简数据库写入测试
"""

import os
from sqlalchemy import create_engine, text

# 从环境变量获取数据库URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("=" * 70)
print("💾 最简数据库写入测试")
print("=" * 70)

# 创建数据库引擎
engine = create_engine(DB_URL, pool_pre_ping=True)

try:
    # 测试连接
    print("\n1️⃣ 测试数据库连接...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print(f"   ✅ 连接成功: {result.fetchone()}")
    
    # 检查表
    print("\n2️⃣ 检查表是否存在...")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'finedatalink' 
                AND table_name = 'sales_forecast_history'
            )
        """))
        exists = result.fetchone()[0]
        print(f"   表存在: {exists}")
    
    # 检查数据
    print("\n3️⃣ 检查当前数据...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
        count = result.fetchone()[0]
        print(f"   总记录数: {count}")
    
    # 查询最新数据
    print("\n4️⃣ 查询最新数据...")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT spu, run_date, forecast_target_date, spu_forecast_value, winner_algo
            FROM finedatalink.sales_forecast_history
            ORDER BY run_date DESC
            LIMIT 3
        """))
        rows = result.fetchall()
        print(f"   最新数据 ({len(rows)}条):")
        for row in rows:
            print(f"      {row}")
    
    print("\n✅ 测试完成!")
    
finally:
    engine.dispose()
