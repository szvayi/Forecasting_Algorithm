#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试简单的数据库查询
"""
import os
import sys
import time
from sqlalchemy import create_engine, text
import pandas as pd

# 添加当前目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

print("🔄 测试简单的数据库查询...")

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
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 AS test"))
        row = result.fetchone()
        print(f"✅ 查询成功: {row}")
    
    # 测试查询表结构
    print("🔄 查询表结构...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM lx_ods.查询订单利润_msku_cny_5年版 LIMIT 1"))
        columns = result.keys()
        print(f"✅ 表结构查询成功，列数: {len(columns)}")
        print(f"✅ 前5列: {list(columns)[:5]}")
    
    engine.dispose()
    print("✅ 测试完成！")
    
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
