#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
逐步测试模块导入
"""
import sys
import os

print("🔄 逐步测试模块导入...")
print(f"Python版本: {sys.version}")
print(f"当前目录: {os.getcwd()}")

# 添加当前目录到Python路径
sys.path.insert(0, os.getcwd())

# 测试1: 导入基本模块
print("\n1. 测试基本模块导入...")
try:
    import pandas as pd
    import numpy as np
    print("✅ 基本模块导入成功")
except Exception as e:
    print(f"❌ 基本模块导入失败: {e}")

# 测试2: 导入sqlalchemy
print("\n2. 测试sqlalchemy导入...")
try:
    from sqlalchemy import create_engine
    print("✅ sqlalchemy导入成功")
except Exception as e:
    print(f"❌ sqlalchemy导入失败: {e}")

# 测试3: 导入src.utils
print("\n3. 测试src.utils导入...")
try:
    from src.utils import helpers
    print("✅ src.utils.helpers导入成功")
except Exception as e:
    print(f"❌ src.utils导入失败: {e}")

# 测试4: 导入src.database
print("\n4. 测试src.database导入...")
try:
    from src.database import repositories
    print("✅ src.database.repositories导入成功")
except Exception as e:
    print(f"❌ src.database导入失败: {e}")

# 测试5: 导入src.forecasting.models
print("\n5. 测试src.forecasting.models导入...")
try:
    from src.forecasting import models
    print("✅ src.forecasting.models导入成功")
except Exception as e:
    print(f"❌ src.forecasting.models导入失败: {e}")

# 测试6: 导入src.forecasting.predictors
print("\n6. 测试src.forecasting.predictors导入...")
try:
    from src.forecasting import predictors
    print("✅ src.forecasting.predictors导入成功")
except Exception as e:
    print(f"❌ src.forecasting.predictors导入失败: {e}")

# 测试7: 导入src.forecasting.main
print("\n7. 测试src.forecasting.main导入...")
try:
    from src.forecasting import main
    print("✅ src.forecasting.main导入成功")
except Exception as e:
    print(f"❌ src.forecasting.main导入失败: {e}")

print("\n✅ 导入测试完成")
