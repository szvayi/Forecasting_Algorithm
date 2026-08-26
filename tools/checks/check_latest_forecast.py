#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查最新的预测数据
"""

import os
import sys
import datetime

print("Checking latest forecast data...")

# 检查数据库中的最新预测数据
import psycopg2

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

print(f"Database URL: {DB_URL}")

try:
    # 解析连接字符串
    import urllib.parse
    parsed = urllib.parse.urlparse(DB_URL)
    host = parsed.hostname
    port = parsed.port
    database = parsed.path[1:]
    user = parsed.username
    password = parsed.password
    
    # 连接数据库
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )
    
    cursor = conn.cursor()
    
    # 检查最新的预测数据
    print("\nChecking latest forecast data...")
    cursor.execute("""
    SELECT 
        run_date,
        COUNT(*) as record_count,
        COUNT(DISTINCT spu) as spu_count,
        MIN(forecast_target_date) as min_date,
        MAX(forecast_target_date) as max_date
    FROM finedatalink.sales_forecast_history
    GROUP BY run_date
    ORDER BY run_date DESC
    LIMIT 5
    """)
    
    results = cursor.fetchall()
    if results:
        print("Recent forecast runs:")
        for row in results:
            print(f"  Run Date: {row[0]}, Records: {row[1]}, SPUs: {row[2]}, Date Range: {row[3]} to {row[4]}")
    else:
        print("  No forecast data found")
    
    # 检查今天的预测数据
    today = datetime.date.today()
    print(f"\nChecking forecast data for today ({today})...")
    cursor.execute("""
    SELECT 
        spu,
        COUNT(*) as record_count,
        winner_algo,
        AVG(validation_wmape) as avg_wmape
    FROM finedatalink.sales_forecast_history
    WHERE run_date = %s
    GROUP BY spu, winner_algo
    ORDER BY spu
    """, (today,))
    
    results = cursor.fetchall()
    if results:
        print(f"  Found {len(results)} SPU records for today:")
        for row in results:
            print(f"    SPU: {row[0]}, Records: {row[1]}, Winner: {row[2]}, Avg WMAPE: {row[3]:.4f}")
    else:
        print("  No forecast data found for today")
    
    cursor.close()
    conn.close()
    print("\n✅ Database check completed successfully")
    
except Exception as e:
    print(f"❌ Database check failed: {e}")
    import traceback
    traceback.print_exc()

print("Database check completed.")
