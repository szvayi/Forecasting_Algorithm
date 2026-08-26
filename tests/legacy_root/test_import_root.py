#!/usr/bin/env python3
"""
测试从根目录下的main.py导入函数
"""
import os
import sys

# 确保使用根目录作为工作目录
os.chdir(os.path.abspath(os.path.dirname(__file__)))
print(f"当前工作目录: {os.getcwd()}")
print(f"Python路径: {sys.path}")

print("\n测试导入根目录下的main.py...")
try:
    from main import get_data_from_db, process_single_spu, save_to_database
    print("✓ 成功导入根目录下的main.py中的函数")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成!")
