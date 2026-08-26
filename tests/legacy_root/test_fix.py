#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试修复：验证make_features_for_prediction不再删除NaN值
"""
import sys
sys.path.insert(0, 'c:\\Users\\VY0814\\Forecasting_Algorithm')

import pandas as pd
import numpy as np
from src.forecasting.models import FeatureEngineer

def test_feature_engineer():
    print("=" * 60)
    print("测试 FeatureEngineer 修复")
    print("=" * 60)
    
    # 创建测试数据
    fe = FeatureEngineer()
    train = pd.Series(
        [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210],
        index=pd.date_range('2024-01-01', periods=12, freq='W')
    )
    
    print(f"\n1. 训练数据: {len(train)} 周")
    print(train.values)
    
    # 训练特征工程
    X, y = fe.make_features(pd.DataFrame(train))
    print(f"\n2. 训练特征形状: {X.shape}")
    print(f"   特征名称: {fe.feature_names}")
    
    # 创建预测数据（16周）
    future_dates = pd.date_range('2024-03-25', periods=16, freq='W')
    future_df = pd.DataFrame(index=future_dates, columns=['y'])
    future_df['y'] = 0
    
    print(f"\n3. 预测数据: {len(future_df)} 周")
    print(f"   日期范围: {future_dates[0]} 至 {future_dates[-1]}")
    
    # 生成预测特征
    X_future, y_future = fe.make_features_for_prediction(future_df)
    print(f"\n4. 预测特征形状: {X_future.shape}")
    
    # 验证关键修复点
    if X_future.shape[0] == 16:
        print(f"   ✅ 修复成功！预测特征行数正确: {X_future.shape[0]} == 16")
    else:
        print(f"   ❌ 修复失败！预测特征行数错误: {X_future.shape[0]} != 16")
        return False
    
    # 验证没有NaN值
    nan_count = X_future.isna().sum().sum()
    if nan_count == 0:
        print(f"   ✅ 没有NaN值")
    else:
        print(f"   ⚠️ 存在 {nan_count} 个NaN值")
    
    print("\n" + "=" * 60)
    print("测试通过！修复有效。")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = test_feature_engineer()
    sys.exit(0 if success else 1)
