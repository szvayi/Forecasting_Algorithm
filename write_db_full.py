"""
执行数据库写入 - 完整版
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("=" * 70)
print("Execute database write")
print("=" * 70)

print("\nDatabase URL:", DB_URL)

engine = create_engine(DB_URL, pool_pre_ping=True)

try:
    print("\nStep 1: Test database connection...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("   Connection OK:", result.fetchone())
    
    print("\nStep 2: Check current data...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
        count = result.fetchone()[0]
        print("   Record count:", count)
    
    print("\nStep 3: Read CSV file...")
    csv_file = 'D:/华熠/output/spu_forecast_2026-03-10.csv'
    
    if not os.path.exists(csv_file):
        print("   CSV file not found:", csv_file)
        exit(1)
    
    df = pd.read_csv(csv_file)
    print("   CSV read OK:", len(df), "rows")
    
    print("\nStep 4: Data preprocessing...")
    df['run_date'] = pd.to_datetime(df['run_date']).dt.date
    df['forecast_target_date'] = pd.to_datetime(df['forecast_target_date']).dt.date
    df['data_end_date'] = pd.to_datetime(df['data_end_date']).dt.date
    df['training_weeks'] = df['training_weeks'].astype(int)
    df['has_exog_features'] = df['has_exog_features'].astype(bool)
    print("   Preprocessing OK")
    
    print("\nStep 5: Delete old data...")
    with engine.begin() as conn:
        run_dates = df['run_date'].unique()
        for rd in run_dates:
            del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd")
            result = conn.execute(del_query, {"rd": str(rd)})
            print(f"   Deleted run_date={rd}: {result.rowcount} rows")
    
    print("\nStep 6: Write new data...")
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
    
    print("   Write OK!")
    
    print("\nStep 7: Verify write result...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
        count = result.fetchone()[0]
        print("   Record count after write:", count)
    
    print("\nStep 8: Query latest data...")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT spu, run_date, forecast_target_date, spu_forecast_value, winner_algo
            FROM finedatalink.sales_forecast_history
            ORDER BY run_date DESC
            LIMIT 5
        """))
        rows = result.fetchall()
        print("   Latest data:")
        for row in rows:
            print(f"      {row}")
    
    print("\n" + "=" * 70)
    print("Database write completed!")
    print("=" * 70)
    
finally:
    engine.dispose()
