#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
完整预测流程测试 - 验证SPU预测结果与SKU份额长度匹配问题修复
"""
import sys
sys.path.insert(0, 'c:\\Users\\VY0814\\Forecasting_Algorithm')

import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import pandas as pd
import numpy as np
from datetime import datetime, date
import json

# 导入预测系统组件
from src.forecasting.models import FeatureEngineer, SPUProfiler
from src.forecasting.predictors import run_all_models, predict_future, clean_series, get_current_week_end

def test_process_single_spu():
    """模拟process_single_spu函数的核心逻辑，测试长度匹配问题"""
    print("=" * 70)
    print("测试 SPU 预测流程 - 验证长度匹配修复")
    print("=" * 70)
    
    # 创建模拟数据
    np.random.seed(42)
    dates = pd.date_range('2022-01-01', periods=100, freq='W')
    sales = np.random.normal(100, 20, 100) + np.sin(np.arange(100) * 2 * np.pi / 52) * 30
    sales = np.maximum(sales, 0)
    
    # 创建SPU数据
    df_spu = pd.DataFrame({
        'date': dates,
        'sales': sales,
        'spu': '2141',
        'sku': 'RHNWB2141XXXX',
        'ad_cost': np.random.normal(50, 10, 100),
        'price': np.random.normal(25, 5, 100)
    })
    
    df_spu_idx = df_spu.set_index('date').sort_index()
    series = df_spu_idx['sales'].resample('W').sum()
    
    print(f"\n1. 数据准备:")
    print(f"   - 时间范围: {series.index[0]} 至 {series.index[-1]}")
    print(f"   - 数据点数: {len(series)} 周")
    
    # 清理数据
    series_clean = clean_series(series)
    print(f"   - 清理后数据: {len(series_clean)} 周")
    
    # 分割训练/测试集
    train, test = series_clean.iloc[:-10], series_clean.iloc[-10:]
    print(f"\n2. 训练/测试分割:")
    print(f"   - 训练集: {len(train)} 周")
    print(f"   - 测试集: {len(test)} 周")
    
    # 运行模型竞赛
    print(f"\n3. 模型竞赛中...")
    all_results, base_results = run_all_models(train, test, mode='fast', verbose=True)
    
    if not all_results:
        print("   ❌ 所有模型失败")
        return False
    
    winner = min(all_results, key=lambda x: x['wmape'])
    print(f"   ✅ 胜出模型: {winner['name']} (WMAPE: {winner['wmape']:.2%})")
    
    # 预测未来16周
    print(f"\n4. 预测未来 16 周...")
    final_preds = predict_future(series_clean, winner, 16, None, None, base_results)
    print(f"   - 预测结果长度: {len(final_preds)}")
    print(f"   - 预测值范围: {final_preds.min():.2f} ~ {final_preds.max():.2f}")
    
    # 生成未来日期
    future_dates = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]
    print(f"   - 未来日期长度: {len(future_dates)}")
    
    # 模拟calculate_dynamic_shares
    print(f"\n5. 计算 SKU 动态份额...")
    sku_sales = df_spu_idx.groupby([pd.Grouper(freq='W'), 'sku'])['sales'].sum().unstack(fill_value=0)
    sku_sales = sku_sales.reindex(series_clean.index, fill_value=0)
    
    spu_total = sku_sales.sum(axis=1)
    hist_shares = sku_sales.div(spu_total.replace(0, np.nan), axis=0).ffill().fillna(0)
    
    # 生成未来份额
    future_shares = {}
    for sku in hist_shares.columns:
        series_share = hist_shares[sku]
        if len(series_share) >= 4:
            recent_level = series_share.ewm(span=8, adjust=False).mean().iloc[-1]
            future_vals = [recent_level] * len(future_dates)
            future_shares[sku] = future_vals
        else:
            future_shares[sku] = [series_share.mean() if len(series_share) > 0 else 0] * len(future_dates)
    
    share_df = pd.DataFrame(future_shares, index=future_dates)
    share_df = share_df.div(share_df.sum(axis=1), axis=0).fillna(0)
    
    print(f"   - share_df 形状: {share_df.shape}")
    print(f"   - share_df 行数: {len(share_df)}")
    print(f"   - final_preds 长度: {len(final_preds)}")
    
    # 关键测试点：验证长度匹配
    print(f"\n6. 验证长度匹配...")
    if len(share_df) == len(final_preds):
        print(f"   ✅ 长度匹配！share_df({len(share_df)}) == final_preds({len(final_preds)})")
    else:
        print(f"   ❌ 长度不匹配！share_df({len(share_df)}) != final_preds({len(final_preds)})")
        return False
    
    # 测试SKU预测计算
    print(f"\n7. 计算 SKU 预测销量...")
    try:
        sku_future_df = share_df.multiply(final_preds, axis=0)
        print(f"   ✅ SKU预测计算成功！")
        print(f"   - sku_future_df 形状: {sku_future_df.shape}")
        print(f"\n   SKU预测预览（前3周）:")
        print(sku_future_df.head(3).to_string())
    except Exception as e:
        print(f"   ❌ SKU预测计算失败: {e}")
        return False
    
    print("\n" + "=" * 70)
    print("✅ 测试通过！长度匹配问题已修复。")
    print("=" * 70)
    return True

if __name__ == "__main__":
    try:
        success = test_process_single_spu()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
