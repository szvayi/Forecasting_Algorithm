#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查昨天晚上执行的预测脚本状态
"""

import os
import sys
import datetime

print("Checking last night's forecast execution...")

# 检查数据库中的预测数据
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
    
    # 检查今天所有的预测数据
    today = datetime.date.today()
    print(f"\n1. Checking all forecast data for today ({today})...")
    cursor.execute("""
    SELECT 
        run_date,
        create_time,
        COUNT(*) as record_count,
        COUNT(DISTINCT spu) as spu_count
    FROM finedatalink.sales_forecast_history
    WHERE run_date = %s
    GROUP BY run_date, create_time
    ORDER BY create_time DESC
    """, (today,))
    
    results = cursor.fetchall()
    if results:
        print(f"   Found {len(results)} forecast runs for today:")
        for row in results:
            print(f"     Run Date: {row[0]}, Create Time: {row[1]}, Records: {row[2]}, SPUs: {row[3]}")
    else:
        print("   ❌ No forecast data found for today!")
    
    # 检查昨天晚上的预测数据
    yesterday = today - datetime.timedelta(days=1)
    print(f"\n2. Checking forecast data for yesterday ({yesterday})...")
    cursor.execute("""
    SELECT 
        run_date,
        create_time,
        COUNT(*) as record_count,
        COUNT(DISTINCT spu) as spu_count
    FROM finedatalink.sales_forecast_history
    WHERE run_date = %s
    GROUP BY run_date, create_time
    ORDER BY create_time DESC
    """, (yesterday,))
    
    results = cursor.fetchall()
    if results:
        print(f"   Found {len(results)} forecast runs for yesterday:")
        for row in results:
            print(f"     Run Date: {row[0]}, Create Time: {row[1]}, Records: {row[2]}, SPUs: {row[3]}")
    else:
        print("   ❌ No forecast data found for yesterday!")
    
    # 检查最近的所有预测数据
    print("\n3. Checking recent forecast data (last 3 days)...")
    cursor.execute("""
    SELECT 
        run_date,
        create_time,
        COUNT(*) as record_count,
        COUNT(DISTINCT spu) as spu_count
    FROM finedatalink.sales_forecast_history
    WHERE run_date >= %s
    GROUP BY run_date, create_time
    ORDER BY run_date DESC, create_time DESC
    """, (today - datetime.timedelta(days=3),))
    
    results = cursor.fetchall()
    if results:
        print(f"   Found {len(results)} forecast runs:")
        for row in results:
            print(f"     Run Date: {row[0]}, Create Time: {row[1]}, Records: {row[2]}, SPUs: {row[3]}")
    else:
        print("   ❌ No recent forecast data found!")
    
    cursor.close()
    conn.close()
    print("\n✅ Database check completed")
    
except Exception as e:
    print(f"❌ Database check failed: {e}")
    import traceback
    traceback.print_exc()

print("Check completed.")
