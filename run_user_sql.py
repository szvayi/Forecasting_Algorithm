#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
使用用户提供的SQL运行预测
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import datetime
import time
import pandas as pd
from sqlalchemy import create_engine, text
from src.database.repositories import save_to_database
from src.forecasting.execution_bridge import process_single_spu

def get_user_data(db_url):
    """使用用户提供的SQL获取数据"""
    print("🔄 正在从数据库拉取训练数据，这可能需要一些时间...")
    t0 = time.time()
    
    # 使用用户提供的SQL
    query = """
    with base as (
        select
            ---------------------------维度-----------------------------------
            a."date" as report_date,
            --"seller_store_country-name" AS 店铺名称,
            --"seller_store_country-country" AS 国家,
            --categories AS 分类,
            --principal_names as Listing负责人,
            local_sku,
            case 
                when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
                when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
                when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
                else '-' end as SPU,
            ---------------------------指标------------------------------------
            sum(a.volume) as 销量,
            sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费,
            avg(avg_net_amount) as 平均售价
        from lx_ods.查询订单利润_msku_cny_5年版 a
        group by
            a.date,
            local_sku,
            case 
                when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
                when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
                when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
                else '-' end
    ),
    SPU_list as (
        SELECT '2141' AS SPU UNION ALL 
        SELECT '2062' UNION ALL 
        SELECT '2029' UNION ALL 
        SELECT '2046' UNION ALL 
        SELECT '2026' UNION ALL 
        SELECT '3022' UNION ALL 
        SELECT '1930' UNION ALL 
        SELECT '2214' UNION ALL 
        SELECT '2033' UNION ALL 
        SELECT '2038' UNION ALL 
        SELECT '2208' UNION ALL 
        SELECT '2012' UNION ALL 
        SELECT '3050' UNION ALL 
        SELECT '2176' UNION ALL 
        SELECT '3033' UNION ALL 
        SELECT '2192' UNION ALL 
        SELECT '2213' UNION ALL 
        SELECT '3063' UNION ALL 
        SELECT '2224' UNION ALL 
        SELECT '3058' UNION ALL 
        SELECT '2073' UNION ALL 
        SELECT '3013' UNION ALL 
        SELECT '2165' UNION ALL 
        SELECT '3084' UNION ALL 
        SELECT '1976' UNION ALL 
        SELECT '2197' UNION ALL 
        SELECT '1476' UNION ALL 
        SELECT '1533' UNION ALL 
        SELECT '0887' UNION ALL 
        SELECT '1577' UNION ALL 
        SELECT '1750' UNION ALL 
        SELECT '1512' UNION ALL 
        SELECT '1657' UNION ALL 
        SELECT '1983' UNION ALL 
        SELECT '1318'
    )
    select 
        report_date as date,
        sum(销量) as sales,
        SPU as spu,
        local_sku as sku,
        ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost,
        avg(平均售价) as price
    from base 
    where 
        1=1
        and SPU in (select * from SPU_list)
    group by 
        report_date,
        SPU,
        local_sku
    order by report_date
    """
    
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        print("🔄 执行SQL查询...")
        print(f"🔄 查询长度: {len(query)} 字符")
        t1 = time.time()
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        t2 = time.time()
        print(f"✅ 查询执行完成，耗时: {t2 - t1:.1f} 秒")
        print(f"✅ 数据获取完成！共加载 {len(df)} 行记录，总耗时: {time.time() - t0:.1f} 秒")
        print(f"✅ 唯一SPU数量: {len(df['spu'].unique())}")
        print(f"✅ SPU列表: {sorted(df['spu'].unique())[:10]}...")
        return df
    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        engine.dispose()
        print("🔄 数据库连接已关闭")

def run_user_sql():
    """运行用户SQL版本的预测"""
    print("=" * 80)
    print("🚀 用户SQL版本预测系统")
    print("=" * 80)
    
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    print(f"📅 执行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🗄️ 数据库URL: {DB_URL}")
    
    # 拉取数据
    print("\n🔄 从数据库拉取数据...")
    df_all = get_user_data(DB_URL)
    
    if len(df_all) == 0:
        print("❌ 未获取到数据")
        return
    
    print(f"✅ 数据获取成功，共 {len(df_all)} 行")
    
    # 简单测试：只处理一个SPU
    spus = df_all['spu'].unique()[:1]
    print(f"\n🔄 只处理第一个SPU: {spus[0]}")
    
    exog_cols = [c for c in df_all.columns if c in ['ad_cost', 'price']]
    if exog_cols:
        print(f"   使用外生变量: {exog_cols}")
    
    all_res = []
    
    for i, spu in enumerate(spus, 1):
        print(f"\n{'=' * 70}")
        print(f"[{i}/{len(spus)}] 处理 SPU: {spu}")
        print(f"{'=' * 70}")
        
        res, msg, viz, profile = process_single_spu(
            spu, df_all, mode='fast',  # 使用fast模式加快速度
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
        print(f"📋 预测结果共 {len(final)}
