import sys
sys.path.insert(0, '.')

print("开始测试...")

import pandas as pd
import numpy as np

print("导入pandas和numpy成功")

from src.forecasting.models import FeatureEngineer

print("导入FeatureEngineer成功")

fe = FeatureEngineer()

print("FeatureEngineer实例化成功")

# 创建测试数据
test_data = pd.DataFrame({'y': np.random.randint(50, 150, 100)})

print("创建测试数据成功")

# 测试特征工程
X, y = fe.make_features(test_data)

print(f"特征工程成功，X形状: {X.shape}, y形状: {y.shape}")

print("测试完成!")