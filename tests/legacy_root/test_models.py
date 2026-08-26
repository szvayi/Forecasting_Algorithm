import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from src.forecasting.predictors import run_prophet, run_xgboost, run_lightgbm, run_auto_arima

# 创建测试数据
np.random.seed(42)
train_size = 100
test_size = 10

train = pd.Series(np.random.randint(50, 150, train_size), index=pd.date_range('2023-01-01', periods=train_size, freq='W'))
test = pd.Series(np.random.randint(50, 150, test_size), index=pd.date_range('2024-12-01', periods=test_size, freq='W'))

print("测试数据准备完成")
print(f"训练集大小: {len(train)}")
print(f"测试集大小: {len(test)}")
print(f"训练集前5个值: {train.head().values}")
print(f"测试集前5个值: {test.head().values}")

# 测试Prophet模型
print("\n测试Prophet模型...")
try:
    result = run_prophet(train, test, verbose=True)
    if result:
        print(f"Prophet模型成功! WMAPE: {result['wmape']:.2%}")
    else:
        print("Prophet模型失败")
except Exception as e:
    print(f"Prophet模型异常: {e}")

# 测试XGBoost模型
print("\n测试XGBoost模型...")
try:
    result = run_xgboost(train, test, verbose=True)
    if result:
        print(f"XGBoost模型成功! WMAPE: {result['wmape']:.2%}")
    else:
        print("XGBoost模型失败")
except Exception as e:
    print(f"XGBoost模型异常: {e}")

# 测试LightGBM模型
print("\n测试LightGBM模型...")
try:
    result = run_lightgbm(train, test, verbose=True)
    if result:
        print(f"LightGBM模型成功! WMAPE: {result['wmape']:.2%}")
    else:
        print("LightGBM模型失败")
except Exception as e:
    print(f"LightGBM模型异常: {e}")

# 测试AutoARIMA模型
print("\n测试AutoARIMA模型...")
try:
    result = run_auto_arima(train, test, verbose=True)
    if result:
        print(f"AutoARIMA模型成功! WMAPE: {result['wmape']:.2%}")
    else:
        print("AutoARIMA模型失败")
except Exception as e:
    print(f"AutoARIMA模型异常: {e}")

print("\n测试完成!")