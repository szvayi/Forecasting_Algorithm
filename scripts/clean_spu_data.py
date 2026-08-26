import os
import datetime
from sqlalchemy import create_engine, text

def clean_spu_data(spu):
    db_url = os.getenv("SALES_FORECAST_DB_URL")
    if not db_url:
        print("❌ DB URL not set.")
        return
        
    engine = create_engine(db_url)
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    # Use current_date or explicit date
    sql = text("DELETE FROM finedatalink.sales_forecast_history WHERE spu = :spu AND run_date = :run_date")
    
    with engine.begin() as conn:
        result = conn.execute(sql, {"spu": spu, "run_date": today})
        print(f"✅ Cleaned {result.rowcount} rows for SPU {spu} on {today}")

if __name__ == "__main__":
    clean_spu_data("0887")
