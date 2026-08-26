import sys
sys.path.insert(0, '.')

print("开始测试数据拉取和特征工程...")

import pandas as pd
import numpy as np
from src.forecasting.main import get_data_from_db
from src.forecasting.models import FeatureEngineer

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

# 从数据库获取数据
data, spu_list = get_data_from_db(DB_URL)
print(f"获取到 {len(spu_list)} 个SPU")

# 选择一个SPU进行测试
if spu_list:
    test_spu = spu_list[0]
    print(f"测试 SPU: {test_spu}")
    
    # 获取该SPU的数据
    spu_data = data[data['spu'] == test_spu]
    print(f"SPU {test_spu} 的数据行数: {len(spu_data)}")
    
    # 检查数据结构
    print("数据列名:", spu_data.columns.tolist())
    
    # 尝试创建时间序列
    try:
        # 按周聚合数据
        spu_data['date'] = pd.to_datetime(spu_data['date'])
        weekly_data = spu_data.set_index('date').resample('W').agg({
            'sales': 'sum',
            'price': 'mean',
            'ad_cost': 'sum'
        })
        
        print(f"周度数据行数: {len(weekly_data)}")
        print("周度数据前5行:")
        print(weekly_data.head())
        
        # 测试特征工程
        print("\n测试特征工程...")
        fe = FeatureEngineer()
        
        # 准备数据
        series = weekly_data['sales']
        exog_df = weekly_data[['price', 'ad_cost']] if 'price' in weekly_data.columns and 'ad_cost' in weekly_data.columns else None
        
        # 生成特征
        X, y = fe.make_features(pd.DataFrame(series), exog_df)
        print(f"特征矩阵形状: {X.shape}")
        print("特征列名:", X.columns.tolist())
        print("特征矩阵前5行:")
        print(X.head())
        
    except Exception as e:
        print(f"处理过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
else:
    print("没有找到SPU数据")

print("测试完成!")