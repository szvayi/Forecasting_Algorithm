"""
验证数据库数据脚本
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text


def main():
    """主函数"""
    print("=" * 70)
    print("🔍 验证数据库数据")
    print("=" * 70)
    
    # 从环境变量获取数据库URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # 创建数据库引擎
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    try:
        with engine.connect() as conn:
            # 查询数据
            query = text("""
                SELECT 
                    spu,
                    run_date,
                    forecast_target_date,
                    spu_forecast_value,
                    winner_algo,
                    validation_wmape,
                    training_weeks,
                    has_exog_features,
                    exog_columns
                FROM finedatalink.sales_forecast_history
                WHERE run_date = '2026-03-10'
                ORDER BY spu, forecast_target_date
            """)
            
            df = pd.read_sql(query, con=conn)
            
            print(f"\n📊 查询结果:")
            print(f"   总记录数: {len(df)}")
            print(f"   SPU列表: {df['spu'].unique()}")
            print(f"   列名: {list(df.columns)}")
            
            if len(df) > 0:
                print(f"\n📈 数据预览:")
                print(df[['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value', 'winner_algo', 'validation_wmape']].to_string())
                
                print(f"\n📈 统计信息:")
                print(f"   SPU数量: {df['spu'].nunique()}")
                print(f"   预测日期范围: {df['forecast_target_date'].min()} - {df['forecast_target_date'].max()}")
                print(f"   胜出模型分布:")
                print(df.groupby('winner_algo')['spu'].nunique().sort_values(ascending=False).to_string())
                print(f"   平均WMAPE: {df['validation_wmape'].mean():.2%}")
                print(f"   最大WMAPE: {df['validation_wmape'].max():.2%}")
                print(f"   最小WMAPE: {df['validation_wmape'].min():.2%}")
                
                print(f"\n📈 SKU份额JSON示例:")
                sku_share_query = text("""
                    SELECT spu, forecast_target_date, sku_share_json
                    FROM finedatalink.sales_forecast_history
                    WHERE run_date = '2026-03-10'
                    LIMIT 3
                """)
                sku_df = pd.read_sql(sku_share_query, con=conn)
                for idx, row in sku_df.iterrows():
                    print(f"\n   SPU: {row['spu']}, 日期: {row['forecast_target_date']}")
                    print(f"   SKU份额: {row['sku_share_json'][:200]}...")
                
                print(f"\n✅ 数据库数据验证成功!")
            else:
                print(f"\n❌ 未找到数据，请检查:")
                print(f"   1. 表 finedatalink.sales_forecast_history 是否存在")
                print(f"   2. 数据是否已写入")
                
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
