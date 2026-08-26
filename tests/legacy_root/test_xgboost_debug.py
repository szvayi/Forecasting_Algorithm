import sys
sys.path.insert(0, '.')

print("开始测试模型训练...")

import pandas as pd
import numpy as np
from src.forecasting.models import FeatureEngineer
from xgboost import XGBRegressor

# 创建测试数据
np.random.seed(42)
dates = pd.date_range('2023-01-01', periods=100, freq='W')
train_values = np.random.randint(50, 150, 100)

train = pd.Series(train_values, index=dates)
test = pd.Series(np.random.randint(50, 150, 10), index=pd.date_range('2025-01-01', periods=10, freq='W'))

print(f"训练集大小: {len(train)}")
print(f"测试集大小: {len(test)}")

# 测试FeatureEngineer
print("\n测试FeatureEngineer...")
fe = FeatureEngineer()
X_train, y_train = fe.make_features(pd.DataFrame(train))
print(f"X_train shape: {X_train.shape}, y_train shape: {y_train.shape}")

print("\n测试make_features_for_prediction...")
X_test, y_test = fe.make_features_for_prediction(pd.DataFrame(test))
print(f"X_test shape: {X_test.shape}, y_test shape: {y_test.shape}")

# 测试XGBoost模型
print("\n测试XGBoost模型...")
try:
    model = XGBRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)
    print("XGBoost训练成功")
    
    y_pred = model.predict(X_test)
    print(f"XGBoost预测成功, y_pred shape: {y_pred.shape}")
except Exception as e:
    print(f"XGBoost失败: {e}")
    import traceback
    traceback.print_exc()

print("\n测试完成!")