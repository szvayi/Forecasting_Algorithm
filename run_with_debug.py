#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
运行预测并添加详细调试信息
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import datetime
import pandas as pd
from src.forecasting.execution_bridge import main

def run_with_debug():
    """运行预测并添加详细调试信息"""
    print("=" * 80)
    print("🚀 运行预测系统 (带详细调试)")
    print("=" * 80)
    print(f"📅 执行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🐍 Python版本: {sys.version}")
    print(f"📁 当前目录: {os.getcwd()}")
    
    # 检查环境变量
    db_url = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    print(f"🗄️ 数据库URL: {db_url}")
    
    # 检查必要的模块
    try:
        import psycopg2
        print("✅ psycopg2模块已安装")
    except ImportError:
        print("❌ psycopg2模块未安装")
    
    try:
        from sqlalchemy import create_engine
        print("✅ SQLAlchemy模块已安装")
    except ImportError:
        print("❌ SQLAlchemy模块未安装")
    
    print("\n🔄 开始执行预测...")
    
    try:
        main()
        print("\n✅ 预测执行完成")
    except Exception as e:
        print(f"\n❌ 执行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    run_with_debug()
