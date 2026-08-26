#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试forecasting模块导入
"""
import sys
import os

print("🔄 测试forecasting模块导入...")
print(f"Python版本: {sys.version}")
print(f"当前目录: {os.getcwd()}")

# 添加当前目录到Python路径
sys.path.insert(0, os.getcwd())
print(f"Python路径: {sys.path[:5]}")

try:
    print("🔄 导入src.forecasting...")
    from src.forecasting import main
    print("✅ src.forecasting.main导入成功")
    
except Exception as e:
    print(f"❌ 导入src.forecasting失败: {e}")
    import traceback
    traceback.print_exc()

print("✅ 模块导入测试完成")
