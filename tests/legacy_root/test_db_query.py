#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试数据库查询速度
"""

import os
import sys
import time

print("Testing database query speed...")

# 测试数据库查询
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
    start_time = time.time()
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )
    conn_time = time.time() - start_time
    print(f"✅ Database connected in {conn_time:.2f} seconds")
    
    cursor = conn.cursor()
    
    # 测试简单查询
    print("\nTesting simple query...")
    start_time = time.time()
    cursor.execute("SELECT COUNT(*) FROM finedatalink.t_dd_sales_spu")
    count = cursor.fetchone()[0]
    query_time = time.time() - start_time
    print(f"✅ Query completed in {query_time:.2f} seconds")
    print(f"   Total rows: {count}")
    
    # 测试实际的预测查询（限制返回行数）
    print("\nTesting forecast query (limited)...")
    sql = """
    SELECT
        spu,
        sku,
        date_sale,
        qty_ordered,
        price,
        ad_cost
    FROM
        finedatalink.t_dd_sales_spu
    WHERE
        spu IN (
            '2141', '2062', '2029', '2046', '2026', '3022', '1930', '2214', '2033', '2038',
            '2208', '2012', '3050', '2176', '3033', '2192', '2213', '3063', '2224', '3058',
            '2073', '3013', '2165', '3084', '1976', '2197', '1476', '1533', '0887', '1577',
            '1750', '1512', '1657', '1983', '1318'
        )
    AND
        date_sale >= '2023-01-01'
    ORDER BY
        spu, date_sale
    LIMIT 1000
    """
    
    start_time = time.time()
    cursor.execute(sql)
    rows = cursor.fetchall()
    query_time = time.time() - start_time
    print(f"✅ Forecast query completed in {query_time:.2f} seconds")
    print(f"   Returned {len(rows)} rows")
    
    cursor.close()
    conn.close()
    print("\n✅ Database test completed successfully")
    
except Exception as e:
    print(f"❌ Database test failed: {e}")
    import traceback
    traceback.print_exc()

print("Database test completed.")
