#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
简化版预测脚本，只处理少量SPU
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import datetime
import pandas as pd
from src.forecasting.execution_bridge import get_data_from_db, process_single_spu, save_to_database

def run_simple_forecast():
    """运行简化版预测"""
    print("=" * 80)
    print("🚀 简化版预测系统")
    print("=" * 80)
    
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    print(f"📅 执行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🗄️ 数据库URL: {DB_URL}")
    
    # 拉取数据
    print("\n🔄 从数据库拉取数据...")
    df_all = get_data_from_db(DB_URL)
    
    if len(df_all) == 0:
        print("❌ 未获取到数据")
        return
    
    print(f"✅ 数据获取成功，共 {len(df_all)} 行")
    print(f"✅ 唯一SPU数量: {len(df_all['spu'].unique())}")
    
    # 只处理前3个SPU
    spus = df_all['spu'].unique()[:3]
    print(f"\n🔄 只处理前 {len(spus)} 个SPU: {spus}")
    
    exog_cols = [c for c in df_all.columns if c in ['ad_cost', 'price']]
    if exog_cols:
        print(f"   使用外生变量: {exog_cols}")
    
    all_res = []
    
    for i, spu in enumerate(spus, 1):
        print(f"\n{'=' * 70}")
        print(f"[{i}/{len(spus)}] 处理 SPU: {spu}")
        print(f"{'=' * 70}")
        
        res, msg, viz, profile = process_single_spu(
            spu, df_all, mode='smart',
            exog_cols=exog_cols, collect_viz=False, verbose=True
        )
        
        print(f"\n   📝 结果: {msg}")
        
        if res is not None:
            all_res.append(res)
            print(f"   ✅ 处理成功，预测结果已生成")
        else:
            print(f"   ❌ 处理失败")
    
    if all_res:
        final = pd.concat(all_res, ignore_index=True)
        print(f"\n{'=' * 70}")
        print(f"📊 处理完成！成功: {len(all_res)}/{len(spus)} 个SPU")
        print(f"📋 预测结果共 {len(final)} 行")
        
        # 保存到数据库
        print("\n🔄 保存到数据库...")
        try:
            save_to_database(final, DB_URL)
            print("✅ 数据库保存成功！")
        except Exception as e:
            print(f"❌ 数据库保存失败: {e}")
    
    print("\n✅ 简化版预测完成！")

if __name__ == '__main__':
    run_simple_forecast()
