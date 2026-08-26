#!/usr/bin/env python3
"""测试导入analysis_worker.py"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    print("尝试导入analysis_worker模块...")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src/api')))
    
    # 尝试导入main模块
    print("尝试导入main模块...")
    from main import get_data_from_db, process_single_spu, save_to_database
    print("main模块导入成功！")
    
    # 尝试执行get_data_from_db
    print("尝试连接数据库...")
    DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
    df = get_data_from_db(DB_URL)
    print(f"数据库连接成功，获取到 {len(df)} 条数据")
    
except Exception as e:
    import traceback
    print(f"错误: {str(e)}")
    traceback.print_exc()
