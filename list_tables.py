#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
列出数据库中的表
"""

import os
import sys

print("Listing database tables...")

# 列出数据库表
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
    
    # 列出finedatalink schema中的所有表
    print("\nTables in finedatalink schema:")
    cursor.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'finedatalink' 
    ORDER BY table_name
    """)
    
    tables = cursor.fetchall()
    if tables:
        for table in tables:
            print(f"  - {table[0]}")
    else:
        print("  No tables found in finedatalink schema")
    
    # 列出所有schema
    print("\nAll schemas:")
    cursor.execute("""
    SELECT schema_name 
    FROM information_schema.schemata 
    ORDER BY schema_name
    """)
    
    schemas = cursor.fetchall()
    for schema in schemas:
        print(f"  - {schema[0]}")
    
    cursor.close()
    conn.close()
    print("\n✅ Table listing completed successfully")
    
except Exception as e:
    print(f"❌ Table listing failed: {e}")
    import traceback
    traceback.print_exc()

print("Table listing completed.")
