import os
import sys
import datetime
import pandas as pd
from sqlalchemy import create_engine, text

def monitor_results():
    db_url = os.getenv("SALES_FORECAST_DB_URL")
    if not db_url:
        print("❌ Error: SALES_FORECAST_DB_URL not set.")
        return

    engine = create_engine(db_url)
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    query = f"""
    select spu, validation_wmape, run_date
    from finedatalink.sales_forecast_history
    where run_date = '{today}'
    """
    
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
    except Exception as e:
        print(f"❌ DB Connection Failed: {e}")
        sys.exit(1)

    # 1. Check if run completed (has data)
    if df.empty:
        alert_msg = f"🚨 ALERT: No forecast data found for run_date={today}. Pipeline may have failed."
        print(alert_msg)
        log_alert(alert_msg)
        sys.exit(1)

    # 2. Check Accuracy
    avg_wmape = df['validation_wmape'].mean()
    high_error_spus = df[df['validation_wmape'] > 0.30]
    
    print(f"✅ Monitor: Found {len(df)} SPUs. Avg WMAPE: {avg_wmape:.2%}")
    
    alerts = []
    if avg_wmape > 0.20:
        alerts.append(f"⚠️ High Average Error: {avg_wmape:.2%} (Threshold: 20%)")
    
    if not high_error_spus.empty:
        alerts.append(f"⚠️ {len(high_error_spus)} SPUs have WMAPE > 30%:")
        for _, row in high_error_spus.iterrows():
            alerts.append(f"   - SPU {row['spu']}: {row['validation_wmape']:.2%}")

    if alerts:
        full_msg = "\n".join(alerts)
        print(full_msg)
        log_alert(full_msg)
    else:
        print("✅ All metrics within normal range.")

def log_alert(msg):
    log_file = "logs/alerts.log"
    if not os.path.exists("logs"): os.makedirs("logs")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now()}] {msg}\n")

if __name__ == "__main__":
    monitor_results()
