#!/usr/bin/env python3
"""
部署前检查脚本
检查系统各组件是否正常工作，确保部署到正式环境前的准备工作完成
"""
import os
import sys
import requests
import json
from sqlalchemy import create_engine

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

# 检查项目依赖
def check_dependencies():
    """检查项目依赖是否安装"""
    print("=" * 80)
    print("检查项目依赖...")
    try:
        import pandas
        import numpy
        import sqlalchemy
        import fastapi
        import uvicorn
        import prophet
        import catboost
        print("✅ 所有核心依赖已安装")
        return True
    except ImportError as e:
        print(f"❌ 依赖检查失败: {e}")
        return False

# 检查环境变量
def check_environment_variables():
    """检查环境变量是否配置"""
    print("=" * 80)
    print("检查环境变量...")
    
    required_vars = [
        "SALES_FORECAST_DB_URL",
        "SKU_ACCURACY_THRESHOLD"
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"⚠️  {var} 未设置，将使用默认值")
    
    # 检查默认值
    db_url = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    sku_threshold = os.getenv("SKU_ACCURACY_THRESHOLD", "0.01")
    
    print(f"\n使用的配置:")
    print(f"  数据库URL: {db_url}")
    print(f"  SKU精度阈值: {sku_threshold}")
    return True

# 检查数据库连接
def check_database_connection():
    """检查数据库连接是否正常"""
    print("=" * 80)
    print("检查数据库连接...")
    
    db_url = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute("SELECT 1")
            if result.fetchone():
                print("✅ 数据库连接正常")
                return True
            else:
                print("❌ 数据库连接失败")
                return False
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False

# 检查API服务
def check_api_service():
    """检查API服务是否正常运行"""
    print("=" * 80)
    print("检查API服务...")
    
    api_base = "http://localhost:8000"
    
    # 检查健康状态
    try:
        response = requests.get(f"{api_base}/api/health")
        if response.status_code == 200:
            print("✅ API健康状态正常")
        else:
            print(f"❌ API健康状态异常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ API服务未运行: {e}")
        return False
    
    # 检查分析状态端点
    try:
        response = requests.get(f"{api_base}/api/analysis-status")
        if response.status_code == 200:
            print("✅ 分析状态端点正常")
        else:
            print(f"❌ 分析状态端点异常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 分析状态端点测试失败: {e}")
        return False
    
    return True

# 检查静态文件服务
def check_static_files():
    """检查静态文件服务是否正常"""
    print("=" * 80)
    print("检查静态文件服务...")
    
    api_base = "http://localhost:8000"
    
    # 检查根路径
    try:
        response = requests.get(api_base)
        if response.status_code == 200:
            print("✅ 根路径访问正常")
        else:
            print(f"❌ 根路径访问异常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 根路径访问失败: {e}")
        return False
    
    # 检查前端页面
    try:
        response = requests.get(f"{api_base}/forecast_dashboard.html")
        if response.status_code == 200:
            print("✅ 前端页面访问正常")
        else:
            print(f"❌ 前端页面访问异常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 前端页面访问失败: {e}")
        return False
    
    return True

# 检查文件结构
def check_file_structure():
    """检查项目文件结构是否完整"""
    print("=" * 80)
    print("检查文件结构...")
    
    required_files = [
        "main.py",
        "config_and_utils.py",
        "algorithm_engine.py",
        "src/api/app.py",
        "src/api/analysis_worker.py",
        "forecast_dashboard.html",
        "index.html",
        "requirements.txt"
    ]
    
    all_exist = True
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file} 存在")
        else:
            print(f"❌ {file} 不存在")
            all_exist = False
    
    return all_exist

# 主检查函数
def main():
    """执行所有检查"""
    print("开始部署前检查...")
    print("=" * 80)
    
    checks = [
        ("依赖检查", check_dependencies),
        ("环境变量检查", check_environment_variables),
        ("数据库连接检查", check_database_connection),
        ("API服务检查", check_api_service),
        ("静态文件检查", check_static_files),
        ("文件结构检查", check_file_structure)
    ]
    
    passed_checks = 0
    total_checks = len(checks)
    
    for check_name, check_func in checks:
        print(f"\n执行 {check_name}...")
        if check_func():
            passed_checks += 1
        print()
    
    print("=" * 80)
    print("部署前检查结果汇总:")
    print(f"通过检查: {passed_checks}/{total_checks}")
    
    if passed_checks == total_checks:
        print("✅ 所有检查通过，可以部署到正式环境")
    else:
        print("❌ 部分检查未通过，需要修复后再部署")

if __name__ == "__main__":
    main()
