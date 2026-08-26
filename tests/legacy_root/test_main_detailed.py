#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
详细测试main函数的执行情况
"""
import sys
import os
import traceback

# 添加当前目录到Python路径
sys.path.insert(0, os.getcwd())

print("🔄 开始测试main函数...")

try:
    # 导入模块
    print("🔄 导入模块...")
    from src.forecasting.main import main
    print("✅ 模块导入成功")
    
    # 运行main函数
    print("🔄 运行main函数...")
    main()
    print("✅ main函数运行完成")
    
except Exception as e:
    print(f"❌ 运行失败: {e}")
    traceback.print_exc()
finally:
    print("✅ 测试完成")
