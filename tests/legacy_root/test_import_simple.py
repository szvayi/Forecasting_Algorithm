#!/usr/bin/env python3
"""
简单测试模块导入
"""
import os
import sys

print(f"Python版本: {sys.version}")
print(f"当前工作目录: {os.getcwd()}")
print(f"Python路径: {sys.path}")

print("\n测试导入 src.forecasting...")
try:
    import src.forecasting
    print("✓ 成功导入 src.forecasting")
except Exception as e:
    print(f"✗ 导入 src.forecasting 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成!")
