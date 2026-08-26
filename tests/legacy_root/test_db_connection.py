print('开始测试数据库连接...')

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 获取数据库连接URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
print(f"数据库连接URL: {DB_URL}")

# 测试数据库连接
from sqlalchemy import create_engine, text

try:
    engine = create_engine(DB_URL)
    print("创建引擎成功")
    
    with engine.connect() as conn:
        print("连接成功")
        # 执行一个简单的查询
        result = conn.execute(text("SELECT 1"))
        print(f"查询结果: {result.scalar()}")
        print("测试成功！")
finally:
    engine.dispose()
    print("连接已关闭")

print('测试完成')