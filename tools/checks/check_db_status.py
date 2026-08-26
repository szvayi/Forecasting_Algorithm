#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查数据库连接和数据插入状态
"""
from sqlalchemy import create_engine, text

def check_db_connection():
    """检查数据库连接"""
    print("🔄 检查数据库连接...")
    db_url = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
    
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            # 测试简单查询
            result = conn.execute(text("SELECT 1 as test"))
            print(f"✅ 数据库连接成功! 测试结果: {result.fetchone()[0]}")
        engine.dispose()
        return True
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False

def check_table_exists():
    """检查表是否存在"""
    print("🔄 检查表是否存在...")
    db_url = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
    
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # 检查表是否存在
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.tables 
                    WHERE table_schema = 'finedatalink' 
                    AND table_name = 'sales_forecast_history'
                )
            """))
            exists = result.fetchone()[0]
            if exists:
                print("✅ 表存在")
            else:
                print("❌ 表不存在")
        engine.dispose()
        return exists
    except Exception as e:
        print(f"❌ 检查表失败: {e}")
        return False

def check_record_count():
    """检查记录数"""
    print("🔄 检查记录数...")
    db_url = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
    
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # 检查记录数
            result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
            count = result.fetchone()[0]
            print(f"📊 数据库中的记录数: {count}")
        engine.dispose()
        return count
    except Exception as e:
        print(f"❌ 检查记录数失败: {e}")
        return 0

if __name__ == "__main__":
    print("=" * 70)
    print("📊 数据库状态检查")
    print("=" * 70)
    
    # 检查数据库连接
    if check_db_connection():
        # 检查表是否存在
        if check_table_exists():
            # 检查记录数
            check_record_count()
    
    print("=" * 70)
    print("检查完成!")
    print("=" * 70)
