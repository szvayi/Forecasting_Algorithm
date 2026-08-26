"""
强制执行数据库写入脚本
"""

import os
import datetime
import pandas as pd
from sqlalchemy import create_engine, text


def main():
    """主函数"""
    print("=" * 70)
    print("💾 强制执行数据库写入")
    print("=" * 70)
    
    # 从环境变量获取数据库URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    print(f"\n🔗 数据库URL: {DB_URL}")
    
    # 创建数据库引擎
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    try:
        # 测试连接
        print("\n🔍 测试数据库连接...")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ 数据库连接成功")
        
        # 检查表是否存在
        print("\n🔍 检查表是否存在...")
        check_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'finedatalink' 
                AND table_name = 'sales_forecast_history'
            )
        """)
        with engine.connect() as conn:
            result = conn.execute(check_query)
            table_exists = result.fetchone()[0]
        
        if table_exists:
            print("✅ 表 finedatalink.sales_forecast_history 存在")
        else:
            print("❌ 表 finedatalink.sales_forecast_history 不存在")
            print("   请先创建表结构")
            return
        
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
        
        # 清理旧数据
        print("\n🧹 清理旧数据...")
        with engine.begin() as conn:
            run_dates = df['run_date'].unique()
            for rd in run_dates:
                del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd")
                result = conn.execute(del_query, {"rd": str(rd)})
                print(f"   🧹 已清理 run_date={rd} 旧记录 {result.rowcount} 条")
        
        # 写入新数据
        print("\n🚀 正在写入新数据...")
        with engine.begin() as conn:
            df.to_sql(
                'sales_forecast_history',
                con=conn,
                schema='finedatalink',
                if_exists='append',
                index=False,
                method='multi',
                chunksize=200
            )
        
        print(f"✅ 数据库写入成功! 共写入 {len(df)} 条记录")
        
        # 验证写入结果
        print("\n🔍 验证写入结果...")
        with engine.connect() as conn:
            query = text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history WHERE run_date = '2026-03-10'")
            result = conn.execute(query)
            count = result.fetchone()[0]
        
        print(f"   写入记录数: {count}")
        
        if count == len(df):
            print(f"✅ 验证成功! 数据已成功写入数据库")
        else:
            print(f"❌ 验证失败! 期望 {len(df)} 条，实际 {count} 条")
        
    except Exception as e:
        import traceback
        print(f"❌ 错误: {e}")
        traceback.print_exc()
        
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
