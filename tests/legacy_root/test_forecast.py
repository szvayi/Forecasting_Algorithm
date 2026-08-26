import sys
sys.path.insert(0, '.')

import os
import datetime
from src.forecasting.main import get_data_from_db, process_single_spu, save_to_database

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("Starting test...")

# 测试数据获取
try:
    print("\n1. Testing data retrieval...")
    df_all = get_data_from_db(DB_URL)
    print(f"✓ Data retrieved: {len(df_all)} rows")
    print(f"✓ Unique SPUs: {len(df_all['spu'].unique())}")
    print(f"✓ Sample SPUs: {df_all['spu'].unique()[:5]}")
except Exception as e:
    print(f"✗ Error retrieving data: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试单个SPU处理
try:
    print("\n2. Testing single SPU processing...")
    spu = df_all['spu'].unique()[0]
    print(f"Processing SPU: {spu}")
    result, msg, viz, profile = process_single_spu(spu, df_all, mode='smart', verbose=True)
    print(f"✓ Processing result: {msg}")
    if result is not None:
        print(f"✓ Result shape: {result.shape}")
        print(f"✓ Sample result:\n{result.head()}")
except Exception as e:
    print(f"✗ Error processing SPU: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nTest completed successfully!")
