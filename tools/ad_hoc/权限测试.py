#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from urllib.parse import urlparse

import psycopg2

db_url = os.getenv("SALES_FORECAST_DB_URL")
if not db_url:
    print("缺少环境变量 SALES_FORECAST_DB_URL，参见 ENV.md")
    sys.exit(1)

parsed = urlparse(db_url.replace("postgresql+psycopg2://", "postgresql://", 1))
PG_HOST = parsed.hostname
PG_PORT = parsed.port or 5432
PG_DATABASE = (parsed.path or "/").lstrip("/") or "finedatalink"
PG_USER = parsed.username
PG_PASSWORD = parsed.password

try:
    print("\n🔍 验证权限...\n")

    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
    )

    cur = conn.cursor()

    # 测试 1：查询视图是否存在
    print("=" * 80)
    print("测试 1: 视图是否存在")
    print("=" * 80)

    cur.execute("""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'ads_pur_delivery_summary'
            AND table_schema = 'public'
        );
    """)

    exists = cur.fetchone()[0]
    print(f"  {'✓' if exists else '❌'} 视图存在: {exists}\n")

    cur.close()
    conn.close()
except Exception as e:
    print(f"错误: {e}")
    sys.exit(1)
