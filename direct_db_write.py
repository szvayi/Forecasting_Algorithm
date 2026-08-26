"""
直接执行数据库写入脚本
"""

import os
import datetime
import pandas as pd
from sqlalchemy import create_engine, text
from src.database.repositories import save_to_database


def main():
    """主函数"""
    print("=" * 70)
    print("💾 直接执行数据库写入")
    print("=" * 70)
    
    # 从环境变量获取数据库URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # 读取CSV文件
    OUTPUT_DIR = 'D:/华熠/output'
    csv_file = os.path.join(OUTPUT_DIR, 'spu_forecast_2026-03-10.csv')
    
    print(f"\n📂 读取CSV文件: {csv_file}")
    
    if not os.path.exists(csv_file):
        print(f"❌ CSV文件不存在: {csv_file}")
        return
    
    df = pd.read_csv(csv_file)
    print(f"✅ CSV文件读取成功: {len(df)} 行")
    
    # 数据预处理
    print("\n📊 数据预处理...")
    df['run_date'] = pd.to_datetime(df['run_date']).dt.date
    df['forecast_target_date'] = pd.to_datetime(df['forecast_target_date']).dt.date
    df['data_end_date'] = pd.to_datetime(df['data_end_date']).dt.date
    df['training_weeks'] = df['training_weeks'].astype(int)
    df['has_exog_features'] = df['has_exog_features'].astype(bool)
    df['sku_share_json'] = df['sku_share_json'].astype(str)
    df['best_params'] = df['best_params'].astype(str)
    
    print(f"✅ 数据预处理完成")
    print(f"   列名及类型:\n{df.dtypes.to_string()}")
    print(f"   数据预览:\n{df[['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value']].head(3).to_string()}")
    
    # 写入数据库
    print("\n🚀 正在写入数据库...")
    save_to_database(df, DB_URL)
    
    print("\n" + "=" * 70)
    print("✅ 数据库写入完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
