#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试main模块的依赖导入
"""
import sys
import os

print("🔄 测试main模块的依赖导入...")
print(f"Python版本: {sys.version}")
print(f"当前目录: {os.getcwd()}")

# 添加当前目录到Python路径
sys.path.insert(0, os.getcwd())

# 测试依赖导入
print("\n1. 测试基本依赖...")
try:
    from datetime import datetime
    import os
    import time
    import pandas as pd
    import numpy as np
    import json
    from sqlalchemy import create_engine, text
    print("✅ 基本依赖导入成功")
except Exception as e:
    print(f"❌ 基本依赖导入失败: {e}")

print("\n2. 测试src.utils.helpers...")
try:
    from src.utils import helpers
    print("✅ src.utils.helpers导入成功")
except Exception as e:
    print(f"❌ src.utils.helpers导入失败: {e}")

print("\n3. 测试src.database.repositories...")
try:
    from src.database import repositories
    print("✅ src.database.repositories导入成功")
except Exception as e:
    print(f"❌ src.database.repositories导入失败: {e}")

print("\n4. 测试src.forecasting.models...")
try:
    from src.forecasting import models
    print("✅ src.forecasting.models导入成功")
except Exception as e:
    print(f"❌ src.forecasting.models导入失败: {e}")

print("\n5. 测试src.forecasting.predictors...")
try:
    from src.forecasting import predictors
    print("✅ src.forecasting.predictors导入成功")
except Exception as e:
    print(f"❌ src.forecasting.predictors导入失败: {e}")

print("\n6. 测试src.forecasting.main...")
try:
    from src.forecasting import main
    print("✅ src.forecasting.main导入成功")
except Exception as e:
    print(f"❌ src.forecasting.main导入失败: {e}")

print("\n✅ 依赖测试完成")
