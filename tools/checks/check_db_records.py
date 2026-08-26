#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查数据库记录统计
"""

import pandas as pd
from sqlalchemy import create_engine, text

# 数据库URL
db_url = 'postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink'

print("=" * 80)
print("📊 数据库记录统计")
print("=" * 80)

# 连接数据库
engine = create_engine(db_url, pool_pre_ping=True)
try:
    with engine.connect() as conn:
        # 查询每日记录数
        query = text("""
            SELECT 
                run_date,
                COUNT(*) as record_count,
                COUNT(DISTINCT spu) as spu_count
            FROM finedatalink.sales_forecast_history
            GROUP BY run_date
            ORDER BY run_date DESC
        """)
        
        df = pd.read_sql(query, con=conn)
        
        print("\n📋 每日记录统计:")
        print(df)
        
        # 计算每个SPU的平均记录数
        if not df.empty:
            total_records = df['record_count'].sum()
            total_spus = df['spu_count'].sum()
            avg_records_per_spu = total_records / total_spus if total_spus > 0 else 0
            
            print(f"\n📊 总体统计:")
            print(f"   总记录数: {total_records}")
            print(f"   总SPU数: {total_spus}")
            print(f"   每个SPU平均记录数: {avg_records_per_spu:.1f}")
            
        # 查询今天的详细数据
        query_today = text("""
            SELECT 
                spu,
                COUNT(*) as record_count
            FROM finedatalink.sales_forecast_history
            WHERE run_date = CURRENT_DATE
            GROUP BY spu
            ORDER BY spu
        """)
        
        df_today = pd.read_sql(query_today, con=conn)
        
        print("\n📋 今日各SPU记录数:")
        print(df_today)
        
        if not df_today.empty:
            avg_today = df_today['record_count'].mean()
            print(f"\n📊 今日平均每个SPU记录数: {avg_today:.1f}")
finally:
    engine.dispose()

print("\n" + "=" * 80)
print("🔍 分析完成")
print("=" * 80)
