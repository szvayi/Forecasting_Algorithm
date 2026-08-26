#!/usr/bin/env python3
"""
测试脚本，将输出重定向到文件
"""
import os
import sys

# 重定向标准输出到文件
with open('test_output.txt', 'w', encoding='utf-8') as f:
    sys.stdout = f
    sys.stderr = f
    
    print("开始测试...")
    print(f"Python版本: {sys.version}")
    print(f"当前工作目录: {os.getcwd()}")
    
    # 测试导入
    print("\n测试导入 src.forecasting.main...")
    try:
        from src.forecasting.main import get_data_from_db
        print("✓ 成功导入 get_data_from_db")
    except Exception as e:
        print(f"✗ 导入 get_data_from_db 失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试执行
    print("\n测试执行 get_data_from_db...")
    try:
        db_url = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
        print(f"使用数据库URL: {db_url}")
        df = get_data_from_db(db_url)
        print(f"✓ 成功获取数据，共 {len(df)} 条")
    except Exception as e:
        print(f"✗ 执行 get_data_from_db 失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n测试完成!")

# 恢复标准输出
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print("测试已完成，输出已保存到 test_output.txt 文件中")
