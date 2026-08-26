import pandas as pd
import numpy as np
from prophet import Prophet

# 创建测试数据
dates = pd.date_range(start='2020-01-01', periods=104, freq='W')
values = np.sin(np.arange(104) * 0.1) * 10 + 50 + np.random.randn(104) * 2

df = pd.DataFrame({
    'ds': dates,
    'y': values
})

try:
    # 创建Prophet模型
    model = Prophet()
    
    # 训练模型
    model.fit(df)
    
    # 预测
    future = model.make_future_dataframe(periods=4, freq='W')
    forecast = model.predict(future)
    
    print("Prophet测试成功！")
    print(f"预测结果形状: {forecast.shape}")
    print(f"预测值示例: {forecast['yhat'].tail().values}")
    
except Exception as e:
    print(f"Prophet测试失败: {e}")
    import traceback
    traceback.print_exc()
