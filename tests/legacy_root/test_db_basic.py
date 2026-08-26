import os
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("测试数据库连接和基本数据...")

try:
    # 连接数据库
    engine = create_engine(DB_URL, pool_pre_ping=True)
    print("✓ 数据库连接成功")
    
    # 测试简单查询
    with engine.connect() as conn:
        # 测试数据库是否有数据
        result = conn.execute(text("SELECT COUNT(*) FROM lx_ods.查询订单利润_msku_cny_5年版 LIMIT 1"))
        count = result.fetchone()[0]
        print(f"✓ 数据表有数据: {count} 条记录")
        
        # 测试local_sku字段
        result = conn.execute(text("SELECT local_sku FROM lx_ods.查询订单利润_msku_cny_5年版 LIMIT 10"))
        skus = [row[0] for row in result]
        print(f"✓ 前10个local_sku: {skus}")
    
    engine.dispose()
    print("\n测试完成!")
    
except Exception as e:
    print(f"✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
