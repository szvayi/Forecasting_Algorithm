#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试数据库写入模块
"""

import os
import sys
import pandas as pd
import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import save_to_database

# 数据库URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("=" * 80)
print("🧪 测试数据库写入模块")
print("=" * 80)

# 1. 读取预测结果文件
csv_file = "D:/华熠/output/spu_forecast_2026-03-12.csv"
if not os.path.exists(csv_file):
    print(f"❌ 预测结果文件不存在: {csv_file}")
    sys.exit(1)

print(f"\n📁 读取预测结果文件: {csv_file}")
df = pd.read_csv(csv_file)
print(f"✅ 读取成功！共 {len(df)} 行记录")

# 2. 检查数据结构
print(f"\n📋 数据列: {list(df.columns)}")
print(f"📋 数据预览:")
print(df.head(3))

# 3. 检查必要的列
required_columns = ['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value']
missing_columns = [col for col in required_columns if col not in df.columns]
if missing_columns:
    print(f"\n❌ 缺少必要的列: {missing_columns}")
    sys.exit(1)

print(f"\n✅ 数据结构检查通过")

# 4. 测试数据库写入
print(f"\n🚀 开始测试数据库写入...")
print(f"   数据库URL: {DB_URL}")

try:
    save_to_database(df, DB_URL)
    print(f"\n✅ 数据库写入测试完成！")
except Exception as e:
    print(f"\n❌ 数据库写入测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 5. 验证写入结果
print(f"\n🔍 验证写入结果...")
from sqlalchemy import create_engine, text

engine = create_engine(DB_URL, pool_pre_ping=True)
try:
    with engine.connect() as conn:
        # 查询今天写入的记录
        today = datetime.date.today()
        query = text("""
            SELECT 
                COUNT(*) as record_count,
                COUNT(DISTINCT spu) as spu_count,
                MIN(create_time) as first_insert,
                MAX(create_time) as last_insert
            FROM finedatalink.sales_forecast_history
            WHERE run_date = :today
        """)
        result = conn.execute(query, {"today": today}).fetchone()
        
        print(f"   📊 今日写入统计:")
        print(f"      记录数: {result[0]}")
        print(f"      SPU数量: {result[1]}")
        print(f"      首次插入: {result[2]}")
        print(f"      最后插入: {result[3]}")
        
        if result[0] > 0:
            print(f"\n✅ 数据库写入验证成功！")
        else:
            print(f"\n❌ 数据库写入验证失败：没有找到今日记录")
            
finally:
    engine.dispose()

print("\n" + "=" * 80)
print("🎉 测试完成")
print("=" * 80)
