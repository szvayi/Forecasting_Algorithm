import sys
sys.path.insert(0, '.')

print("开始测试XGBoost模型...")

import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from src.forecasting.models import FeatureEngineer

print("导入XGBoost和FeatureEngineer成功")

# 创建测试数据
np.random.seed(42)
dates = pd.date_range('2023-01-01', periods=100, freq='W')
values = np.random.randint(50, 150, 100)

train = pd.Series(values, index=dates)
test = pd.Series(np.random.randint(50, 150, 10), index=pd.date_range('2025-01-01', periods=10, freq='W'))

print(f"创建测试数据成功，训练集形状: {train.shape}, 测试集形状: {test.shape}")

# 使用FeatureEngineer创建特征
fe = FeatureEngineer()
X_train, y_train = fe.make_features(pd.DataFrame(train))
X_test, _ = fe.make_features_for_prediction(pd.DataFrame(test))

print(f"特征工程成功，X_train形状: {X_train.shape}, X_test形状: {X_test.shape}")

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