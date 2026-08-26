import sys
sys.path.insert(0, '.')

print("开始测试XGBoost模型...")

import pandas as pd
import numpy as np
from xgboost import XGBRegressor

print("导入XGBoost成功")

# 创建简单的测试数据
np.random.seed(42)
X_train = np.random.rand(100, 5)
y_train = np.random.rand(100)
X_test = np.random.rand(10, 5)

print(f"创建测试数据成功，X_train形状: {X_train.shape}, y_train形状: {y_train.shape}, X_test形状: {X_test.shape}")

# 训练XGBoost模型
model = XGBRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)

print("开始训练XGBoost模型...")

model.fit(X_train, y_train)

print("XGBoost模型训练成功!")

# 进行预测
y_pred = model.predict(X_test)

print(f"预测成功，预测结果形状: {y_pred.shape}")
print(f"预测值: {y_pred}")

print("测试完成!")