import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
print("DB:", DB_URL)

engine = create_engine(DB_URL, pool_pre_ping=True)
try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("OK:", result.fetchone())
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
        count = result.fetchone()[0]
        print("Count:", count)
    
    df = pd.read_csv('D:/华熠/output/spu_forecast_2026-03-10.csv')
    print("CSV rows:", len(df))
    
    df['run_date'] = pd.to_datetime(df['run_date']).dt.date
    df['forecast_target_date'] = pd.to_datetime(df['forecast_target_date']).dt.date
    df['data_end_date'] = pd.to_datetime(df['data_end_date']).dt.date
    df['training_weeks'] = df['training_weeks'].astype(int)
    df['has_exog_features'] = df['has_exog_features'].astype(bool)
    
    with engine.begin() as conn:
        run_dates = df['run_date'].unique()
        for rd in run_dates:
            del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd")
            result = conn.execute(del_query, {"rd": str(rd)})
            print("Deleted:", rd, result.rowcount)
    
    with engine.begin() as conn:
        df.to_sql('sales_forecast_history', con=conn, schema='finedatalink', if_exists='append', index=False, method='multi', chunksize=200)
    
    print("Write OK!")
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM finedatalink.sales_forecast_history"))
        count = result.fetchone()[0]
        print("Final count:", count)
        
finally:
    engine.dispose()
