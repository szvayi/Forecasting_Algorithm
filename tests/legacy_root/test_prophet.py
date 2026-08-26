import sys
sys.path.insert(0, '.')

print("开始测试Prophet模型...")

import pandas as pd
import numpy as np
from prophet import Prophet

print("导入Prophet成功")

# 创建测试数据
np.random.seed(42)
dates = pd.date_range('2023-01-01', periods=100, freq='W')
values = np.random.randint(50, 150, 100)

df = pd.DataFrame({'ds': dates, 'y': values})

print(f"创建测试数据成功，形状: {df.shape}")

# 训练Prophet模型
model = Prophet(
    seasonality_mode='multiplicative',
    changepoint_prior_scale=0.1,
    seasonality_prior_scale=10.0,
    changepoint_range=0.8
)

print("开始训练Prophet模型...")

model.fit(df)

print("Prophet模型训练成功!")

# 进行预测
future = model.make_future_dataframe(periods=10, freq='W')
forecast = model.predict(future)

print(f"预测成功，预测结果形状: {forecast.shape}")

print("测试完成!")