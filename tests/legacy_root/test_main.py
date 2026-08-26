#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试main函数的运行状态
"""
import traceback

try:
    print("🔄 导入main函数...")
    from src.forecasting.main import main
    print("✅ 导入成功")
    
    print("🔄 运行main函数...")
    main()
    print("✅ main函数运行成功")
except Exception as e:
    print(f"❌ 运行失败: {e}")
    traceback.print_exc()
