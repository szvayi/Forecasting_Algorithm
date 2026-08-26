#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试数据库数据拉取
"""
import os
import sys
import time
from sqlalchemy import create_engine, text
import pandas as pd

# 添加当前目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

print("🔄 测试数据库数据拉取...")

try:
    # 数据库连接信息
    DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
    print(f"数据库URL: {DB_URL}")
    
    # 测试数据库连接
    print("🔄 连接数据库...")
    engine = create_engine(DB_URL, pool_pre_ping=True)
    print("✅ 数据库连接成功")
    
    # 测试获取数据
    print("🔄 测试获取数据...")
    query = """
    with base as (
        select
        a."date" as report_date,
        a.msku as local_sku,
        case 
        when substring(a.msku,1,5)='RHNWB' then substring(a.msku,6,4)
        when substring(a.msku,1,2)='VY' then substring(a.msku,5,4)
        when substring(a.msku,1,2)='WB' then substring(a.msku,3,4)
        else '-' end as SPU,
        sum(afn_amount+mfn_amount+promotion_discount+refund_amount+cost_of_points_granted+inventory_credit+shared_fba_liquidation_proceeds+shared_fba_liquidation_proceeds_adjustments
        +shared_amazon_shipping_reimbursement+shared_safe_t_reimbursement+shared_netco_transaction+shared_reimbursements+shared_clawbacks+shared_commingling_vat_income+gift_wrap_credits
        +a_to_z_guarantee_claims+shared_others+shipping_cost) as 销售额,
        sum(a.volume) as 销量,
        avg(avg_net_amount) as 平均售价,
        sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        where a."date" >= '2025-01-01' and a."date" <= '2025-01-31'
        group by 1,2,3
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
        SELECT '887' UNION ALL 
        SELECT '1577' UNION ALL 
        SELECT '1750' UNION ALL 
        SELECT '1512' UNION ALL 
        SELECT '1657' UNION ALL 
        SELECT '1983' UNION ALL 
        SELECT '1318'
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
    from base 
    where 1=1 and SPU in (select SPU from SPU_list)
    group by report_date, SPU, local_sku
    order by report_date
    limit 100
    """
    
    t0 = time.time()
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    print(f"✅ 数据获取成功: {len(df)} 条记录，耗时: {time.time() - t0:.1f} 秒")
    print(f"✅ 发现 {len(df['spu'].unique())} 个SPU")
    print("✅ SPU列表:", df['spu'].unique())
    
    engine.dispose()
    print("✅ 测试完成！")
    
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
