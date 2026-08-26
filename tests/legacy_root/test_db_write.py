import os
import datetime
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 获取数据库连接URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print(f"数据库连接URL: {DB_URL}")

# 创建测试数据
test_data = {
    'spu': ['1234', '5678'],
    'run_date': [datetime.date.today(), datetime.date.today()],
    'forecast_target_date': [datetime.date.today() + datetime.timedelta(days=7), datetime.date.today() + datetime.timedelta(days=14)],
    'spu_forecast_value': [100.5, 200.75],
    'sku_share_json': ['{"sku1": 0.5, "sku2": 0.5}', '{"sku3": 0.6, "sku4": 0.4}'],
    'seasonal_factors_json': '{"week_1": 1.0, "week_2": 1.1}',
    'sku_accuracy_json': '{"sku1": {"wmape": 0.1, "total_sales": 100, "weight_in_spu": 0.5}}',
    'winner_algo': 'XGBoost',
    'validation_wmape': 0.15,
    'best_params': '{"n_estimators": 100, "max_depth": 5}',
    'has_exog_features': True,
    'exog_columns': 'ad_cost,price',
    'training_weeks': 52,
    'data_end_date': datetime.date.today() - datetime.timedelta(days=1)
}

df_test = pd.DataFrame(test_data)
print(f"测试数据:\n{df_test}")

# 测试数据库写入
def test_db_write(df, db_url):
    print("\n测试数据库写入...")
    
    # 所有日期列强制转成 Python 原生 date，兼容 PostgreSQL DATE 类型
    for col in ['run_date', 'forecast_target_date', 'data_end_date']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.date

    df['sku_share_json']    = df['sku_share_json'].astype(str)
    df['sku_accuracy_json'] = df['sku_accuracy_json'].astype(str)
    df['best_params']       = df['best_params'].astype(str)
    df['training_weeks']    = df['training_weeks'].astype(int)
    df['has_exog_features'] = df['has_exog_features'].astype(bool)

    # 检查列名是否与数据库表结构匹配
    expected_columns = ['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value', 
                       'sku_share_json', 'seasonal_factors_json', 'sku_accuracy_json', 
                       'winner_algo', 'validation_wmape', 'best_params', 'has_exog_features', 
                       'exog_columns', 'training_weeks', 'data_end_date']
    
    actual_columns = list(df.columns)
    missing_columns = [col for col in expected_columns if col not in actual_columns]
    extra_columns = [col for col in actual_columns if col not in expected_columns]
    
    print(f"   预期列: {expected_columns}")
    print(f"   实际列: {actual_columns}")
    if missing_columns:
        print(f"   缺少列: {missing_columns}")
    if extra_columns:
        print(f"   多余列: {extra_columns}")

    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
        pool_size=1,
        max_overflow=0,
        pool_recycle=300
    )
    try:
        with engine.begin() as conn:
            # 检查表是否存在
            check_table_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'finedatalink' 
                AND table_name = 'sales_forecast_history'
            )
            """)
            table_exists = conn.execute(check_table_query).scalar()
            print(f"   表是否存在: {table_exists}")
            
            if not table_exists:
                print("   表不存在，创建表结构...")
                # 创建表结构
                create_table_query = text("""
                CREATE TABLE IF NOT EXISTS finedatalink.sales_forecast_history (
                    id SERIAL PRIMARY KEY,
                    spu VARCHAR(50) NOT NULL,
                    run_date DATE NOT NULL,
                    forecast_target_date DATE NOT NULL,
                    spu_forecast_value NUMERIC(18,4) NOT NULL,
                    sku_share_json TEXT,
                    seasonal_factors_json TEXT,
                    sku_accuracy_json TEXT,
                    winner_algo VARCHAR(100),
                    validation_wmape NUMERIC(10,4),
                    best_params TEXT,
                    has_exog_features BOOLEAN,
                    exog_columns VARCHAR(255),
                    training_weeks INTEGER,
                    data_end_date DATE
                )
                """)
                conn.execute(create_table_query)
                print("   表创建成功")
            
            # 清理旧记录
            run_dates = df['run_date'].unique()
            for rd in run_dates:
                del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd")
                result = conn.execute(del_query, {"rd": rd})
                print(f"   已清理 run_date={rd} 旧记录 {result.rowcount} 条，准备幂等写入...")

            # 写入数据
            print("   开始写入数据...")
            # 只选择预期的列
            df = df[expected_columns]
            print(f"   写入列: {list(df.columns)}")
            
            # 写入数据
            df.to_sql(
                'sales_forecast_history',
                con=conn,
                schema='finedatalink',
                if_exists='append',
                index=False,
                method='multi'
            )
            
            # 验证数据是否写入成功
            count_query = text("""
            SELECT COUNT(*) FROM finedatalink.sales_forecast_history WHERE run_date = :rd
            """)
            count = conn.execute(count_query, {"rd": run_dates[0]}).scalar()
            print(f"   验证写入成功，共 {count} 条记录")
        
        print("数据库写入测试成功!")
        return True

    except Exception as e:
        import traceback
        print("数据库写入测试失败，详细错误如下:")
        traceback.print_exc()
        return False
    finally:
        engine.dispose()

# 运行测试
success = test_db_write(df_test, DB_URL)
print(f"测试结果: {'成功' if success else '失败'}")