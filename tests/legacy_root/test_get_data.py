#!/usr/bin/env python3
"""
测试get_data_from_db函数
"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

print("测试导入 get_data_from_db...")
try:
    from src.forecasting.main import get_data_from_db
    print("✓ 成功导入 get_data_from_db")
except Exception as e:
    print(f"✗ 导入 get_data_from_db 失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n测试执行 get_data_from_db...")
try:
    db_url = "postgresql://postgres:password@localhost:5432/forecasting"
    print(f"使用数据库URL: {db_url}")
    df = get_data_from_db(db_url)
    print(f"✓ 成功获取数据，共 {len(df)} 条")
except Exception as e:
    print(f"✗ 执行 get_data_from_db 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成!")
