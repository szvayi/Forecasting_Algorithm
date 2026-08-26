#!/usr/bin/env python
# -*- coding: utf-8 -*-

import psycopg2

PG_HOST = "192.168.1.226"
PG_PORT = 5432
PG_DATABASE = "finedatalink"
PG_USER = "ai_reader"
PG_PASSWORD = "ai_reader_pwd"

try:
    print("\n🔍 验证权限...\n")

    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD
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

    # 测试 2：查询记录数
    print("=" * 80)
    print("测试 2: 查询视图数据")
    print("=" * 80)

    cur.execute("SELECT COUNT(*) FROM public.ads_pur_delivery_summary;")
    count = cur.fetchone()[0]
    print(f"  ✓ 成功查询！")
    print(f"  记录数: {count}\n")

    # 测试 3：查询字段
    print("=" * 80)
    print("测试 3: 查询样本数据")
    print("=" * 80)

    cur.execute("""
        SELECT 
            单据日期,
            业务类型,
            供应商,
            物料名称,
            环节,
            单据数量,
            准交分母,
            准交分子,
            在途数量_逾期,
            期间
        FROM public.ads_pur_delivery_summary 
        LIMIT 5;
    """)

    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

    print(f"  列: {', '.join(columns)}\n")
    print(f"  样本行数: {len(rows)}\n")

    if rows:
        for i, row in enumerate(rows, 1):
            print(f"    行 {i}: {row[0]} | {row[1]} | {row[2]} | {row[3]}")

    print("\n✅ 所有权限验证成功！\n")

    cur.close()
    conn.close()

except Exception as e:
    print(f"\n❌ 权限验证失败: {e}\n")
    import traceback

    traceback.print_exc()