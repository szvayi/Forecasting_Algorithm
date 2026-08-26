import os
from sqlalchemy import create_engine, text

# 数据库连接URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("测试数据库连接...")
try:
    engine = create_engine(DB_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        # 执行一个简单的查询
        result = conn.execute(text("SELECT 1"))
        print(f"✅ 数据库连接成功! 结果: {result.fetchone()}")
    engine.dispose()
except Exception as e:
    print(f"❌ 数据库连接失败: {str(e)}")

print("测试完成。")