#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 lx_ods 表是否存在
"""

import os
import sys

print("Testing lx_ods table...")

# 测试 lx_ods 表
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
    
    # 测试 lx_ods 表
    print("\nTesting lx_ods.查询订单利润_msku_cny_5年版 table...")
    
    # 先检查 lx_ods schema 是否存在
    cursor.execute("""
    SELECT EXISTS (
        SELECT 1 
        FROM information_schema.schemata 
        WHERE schema_name = 'lx_ods'
    )
    """)
    schema_exists = cursor.fetchone()[0]
    print(f"lx_ods schema exists: {schema_exists}")
    
    if schema_exists:
        # 检查表是否存在
        cursor.execute("""
        SELECT EXISTS (
            SELECT 1 
            FROM information_schema.tables 
            WHERE table_schema = 'lx_ods' 
            AND table_name = '查询订单利润_msku_cny_5年版'
        )
        """)
        table_exists = cursor.fetchone()[0]
        print(f"lx_ods.查询订单利润_msku_cny_5年版 table exists: {table_exists}")
        
        if table_exists:
            # 测试简单查询
            print("\nTesting simple query on the table...")
            cursor.execute("""
            SELECT COUNT(*) 
            FROM lx_ods.查询订单利润_msku_cny_5年版 
            WHERE date >= '2023-01-01' 
            LIMIT 10
            """)
            count = cursor.fetchone()[0]
            print(f"✅ Query returned {count} rows")
    
    cursor.close()
    conn.close()
    print("\n✅ Table test completed successfully")
    
except Exception as e:
    print(f"❌ Table test failed: {e}")
    import traceback
    traceback.print_exc()

print("Table test completed.")
