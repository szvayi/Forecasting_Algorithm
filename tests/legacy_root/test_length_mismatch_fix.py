#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试长度不匹配问题的修复
"""
import pandas as pd
import numpy as np
import json
from src.forecasting.main import calculate_dynamic_shares

def create_test_data():
    """创建测试数据"""
    # 创建日期范围
    dates = pd.date_range('2025-01-01', '2025-12-31', freq='D')
    
    # 创建SPU 1318的数据
    spu = '1318'
    
    # 创建多个SKU
    skus = ['SKU1', 'SKU2', 'SKU3']
    
    # 创建销售数据
    data = []
    for date in dates:
        for sku in skus:
            # 生成随机销售数据
            sales = np.random.randint(10, 100)
            data.append({
                'date': date,
                'spu': spu,
                'sku': sku,
                'sales': sales
            })
    
    df = pd.DataFrame(data)
    return df, spu

def test_calculate_dynamic_shares():
    """测试calculate_dynamic_shares函数"""
    print("=" * 70)
    print("📊 测试长度不匹配问题修复")
    print("=" * 70)
    
    # 创建测试数据
    df, spu = create_test_data()
    
    # 准备数据
    df_spu_idx = df.set_index('date').sort_index()
    
    # 计算SPU周销售额
    spu_sales_weekly = df_spu_idx.groupby(pd.Grouper(freq='W'))['sales'].sum()
    
    # 创建未来日期
    future_dates = pd.date_range('2026-01-01', '2026-04-01', freq='W')
    
    print(f"测试 SPU: {spu}")
    print(f"历史数据周数: {len(spu_sales_weekly)}")
    print(f"未来预测周数: {len(future_dates)}")
    
    try:
        # 调用修复后的函数
        json_list, future_df = calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates)
        
        print(f"✅ 函数执行成功!")
        print(f"生成的JSON列表长度: {len(json_list)}")
        print(f"生成的未来份额DataFrame形状: {future_df.shape}")
        
        # 验证长度匹配
        if len(json_list) == len(future_dates):
            print("✅ 长度匹配验证通过!")
        else:
            print("❌ 长度匹配验证失败!")
            print(f"预期长度: {len(future_dates)}, 实际长度: {len(json_list)}")
        
        return True
    except Exception as e:
        print(f"❌ 函数执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_calculate_dynamic_shares()
    print("=" * 70)
    print("测试完成!")
    print("=" * 70)
