import sys
sys.path.insert(0, '.')

print("开始测试模型训练...")

import pandas as pd
import numpy as np
from src.forecasting.predictors import run_prophet, run_xgboost, run_lightgbm

# 创建测试数据
np.random.seed(42)
dates = pd.date_range('2023-01-01', periods=100, freq='W')
train_values = np.random.randint(50, 150, 100)

train = pd.Series(train_values, index=dates)
test = pd.Series(np.random.randint(50, 150, 10), index=pd.date_range('2025-01-01', periods=10, freq='W'))

print(f"训练集大小: {len(train)}")
print(f"测试集大小: {len(test)}")
print(f"训练集前5个值: {train.head().values}")
print(f"测试集前5个值: {test.head().values}")

# 测试Prophet模型
print("\n测试Prophet模型...")
result = run_prophet(train, test, verbose=True)
if result:
    print(f"Prophet模型成功! WMAPE: {result['wmape']:.2%}")
else:
    print("Prophet模型失败")

# 测试XGBoost模型
print("\n测试XGBoost模型...")
result = run_xgboost(train, test, verbose=True)
if result:
    print(f"XGBoost模型成功! WMAPE: {result['wmape']:.2%}")
else:
    print("XGBoost模型失败")

# 测试LightGBM模型
print("\n测试LightGBM模型...")
result = run_lightgbm(train, test, verbose=True)
if result:
    print(f"LightGBM模型成功! WMAPE: {result['wmape']:.2%}")
else:
    print("LightGBM模型失败")

print("\n测试完成!")