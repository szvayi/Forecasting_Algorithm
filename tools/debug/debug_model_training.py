import sys
sys.path.insert(0, '.')

print("开始调试模型训练问题...")

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
import warnings
warnings.filterwarnings('ignore')

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

# 从数据库加载SPU 2141的数据
print("从数据库加载SPU 2141的数据...")
engine = create_engine(DB_URL, pool_pre_ping=True)

SPU = '2141'
query = f"""
SELECT date, spu, msku, sales, price, ad_cost
FROM finedatalink.sales_forecast_history
WHERE spu = '{SPU}'
ORDER BY date
"""

try:
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"查询结果: {len(df)} 行")
    print(df.columns.tolist())
    print(df.head())
    
    # 尝试处理数据
    print("\n开始处理数据...")
    df_idx = df.set_index('date').sort_index()
    
    series = df_idx['sales'].resample('W').sum()
    print(f"销量序列长度: {len(series)}")
    
    # 检查是否有足够的数据
    if len(series) < 30:
        print("数据不足30周")
    else:
        # 尝试使用XGBoost模型
        print("\n尝试使用XGBoost模型...")
        from src.forecasting.models import FeatureEngineer
        from xgboost import XGBRegressor
        
        train = series.iloc[:-10]
        test = series.iloc[-10:]
        
        print(f"训练集大小: {len(train)}")
        print(f"测试集大小: {len(test)}")
        
        # 创建特征
        fe = FeatureEngineer()
        X_train, y_train = fe.make_features(pd.DataFrame(train), None)
        print(f"X_train shape: {X_train.shape}")
        
        X_test, y_test = fe.make_features_for_prediction(pd.DataFrame(test), None)
        print(f"X_test shape: {X_test.shape}")
        
        # 训练模型
        model = XGBRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)
        model.fit(X_train, y_train)
        
        # 预测
        y_pred = model.predict(X_test)
        print(f"y_pred shape: {y_pred.shape}")
        print(f"y_test shape: {y_test.shape}")
        
        print("\nXGBoost模型成功!")
        
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

engine.dispose()
print("\n测试完成!")