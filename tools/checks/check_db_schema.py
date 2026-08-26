#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查数据库表结构
"""

import os
import sys

print("Checking database schema...")

# 检查数据库表结构
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
    
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Database: {database}")
    
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
    print("\nChecking if table exists...")
    cursor.execute("""
    SELECT EXISTS (
        SELECT 1 
        FROM information_schema.tables 
        WHERE table_schema = 'finedatalink' 
        AND table_name = 'sales_forecast_history'
    )
    """)
    exists = cursor.fetchone()[0]
    print(f"Table exists: {exists}")
    
    if exists:
        # 检查表结构
        print("\nTable structure:")
        cursor.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'finedatalink' 
        AND table_name = 'sales_forecast_history'
        ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()
        for col_name, col_type in columns:
            print(f"  {col_name}: {col_type}")
    
    cursor.close()
    conn.close()
    print("\n✅ Schema check completed")
    
except Exception as e:
    print(f"❌ Schema check failed: {e}")
    import traceback
    traceback.print_exc()

print("Schema check completed.")
