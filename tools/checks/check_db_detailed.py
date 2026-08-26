#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查数据库中的预测数据情况
"""

import os
import sys
import datetime

print("Checking database forecast data...")

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
    
    # 检查表是否存在
    print("\n1. Checking if table exists...")
    cursor.execute("""
    SELECT EXISTS (
        SELECT 1 
        FROM information_schema.tables 
        WHERE table_schema = 'finedatalink' 
        AND table_name = 'sales_forecast_history'
    )
    """)
    table_exists = cursor.fetchone()[0]
    print(f"   Table exists: {table_exists}")
    
    if not table_exists:
        print("   ❌ Table does not exist!")
        conn.close()
        sys.exit(1)
    
    # 检查表中的总记录数
    print("\n2. Checking total records in table...")
    cursor.execute("SELECT COUNT(*) FROM finedatalink.sales_forecast_history")
    total_count = cursor.fetchone()[0]
    print(f"   Total records: {total_count}")
    
    # 检查最近的预测日期
    print("\n3. Checking recent forecast dates...")
    cursor.execute("""
    SELECT DISTINCT run_date 
    FROM finedatalink.sales_forecast_history 
    ORDER BY run_date DESC 
    LIMIT 10
    """)
    dates = cursor.fetchall()
    if dates:
        print("   Recent run dates:")
        for date in dates:
            print(f"     - {date[0]}")
    else:
        print("   ❌ No run dates found!")
    
    # 检查今天的预测数据
    today = datetime.date.today()
    print(f"\n4. Checking forecast data for today ({today})...")
    cursor.execute("""
    SELECT COUNT(*) 
    FROM finedatalink.sales_forecast_history 
    WHERE run_date = %s
    """, (today,))
    today_count = cursor.fetchone()[0]
    print(f"   Today's records: {today_count}")
    
    # 检查昨天的预测数据
    yesterday = today - datetime.timedelta(days=1)
    print(f"\n5. Checking forecast data for yesterday ({yesterday})...")
    cursor.execute("""
    SELECT COUNT(*) 
    FROM finedatalink.sales_forecast_history 
    WHERE run_date = %s
    """, (yesterday,))
    yesterday_count = cursor.fetchone()[0]
    print(f"   Yesterday's records: {yesterday_count}")
    
    # 检查最近一周的预测数据
    print("\n6. Checking forecast data for last 7 days...")
    cursor.execute("""
    SELECT 
        run_date,
        COUNT(*) as record_count,
        COUNT(DISTINCT spu) as spu_count
    FROM finedatalink.sales_forecast_history
    WHERE run_date >= %s
    GROUP BY run_date
    ORDER BY run_date DESC
    """, (today - datetime.timedelta(days=7),))
    
    recent_data = cursor.fetchall()
    if recent_data:
        print("   Recent forecast data:")
        for row in recent_data:
            print(f"     Date: {row[0]}, Records: {row[1]}, SPUs: {row[2]}")
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
