#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试数据库查询性能
"""
import os
import sys
import time
from sqlalchemy import create_engine, text
import pandas as pd

# 添加当前目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

print("🔄 测试数据库查询性能...")

try:
    # 数据库连接信息
    DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
    print(f"数据库URL: {DB_URL}")
    
    # 测试数据库连接
    print("🔄 连接数据库...")
    engine = create_engine(DB_URL, pool_pre_ping=True)
    print("✅ 数据库连接成功")
    
    # 测试简单查询
    print("🔄 执行简单查询...")
    query = """
    select 
        a."date" as report_date,
        a.msku as local_sku,
        case 
        when substring(a.msku,1,5)='RHNWB' then substring(a.msku,6,4)
        when substring(a.msku,1,2)='VY' then substring(a.msku,5,4)
        when substring(a.msku,1,2)='WB' then substring(a.msku,3,4)
        else '-' end as SPU,
        sum(a.volume) as 销量
    from lx_ods.查询订单利润_msku_cny_5年版 a 
    where a."date" >= '2024-01-01' and a."date" <= '2026-02-28' 
    and (substring(a.msku,1,5)='RHNWB' or substring(a.msku,1,2)='VY' or substring(a.msku,1,2)='WB')
    group by 1,2,3
    limit 100
    """
    
    t0 = time.time()
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    print(f"✅ 查询执行完成，耗时: {time.time() - t0:.1f} 秒")
    df.columns = [col.lower() for col in df.columns]
    print(f"✅ 结果行数: {len(df)}")
    print(f"✅ 唯一SPU数量: {len(df['spu'].unique())}")
    print(f"✅ SPU列表: {df['spu'].unique()[:10]}...")
    
    engine.dispose()
    print("✅ 测试完成！")
    
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
