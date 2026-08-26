import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine, text
from sklearn.linear_model import LinearRegression

def analyze_trends(spus, db_url):
    engine = create_engine(db_url, pool_pre_ping=True)
    
    # 1. Fetch historical data for target SPUs
    in_list = ",".join([f"'{s}'" for s in spus])
    query = f"""
    with base as (
        select
        a."date" as report_date,
        local_sku,
        case 
        when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
        when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
        when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
        else '-' end as SPU,
        sum(a.volume) as sales
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        group by 1,2,3
    )
    select report_date, local_sku, sales
    from base
    where SPU in ({in_list})
    and report_date >= '2023-01-01' -- Focus on recent 3 years
    order by report_date
    """
    
    print(f"🔄 Fetching data for SPUs: {spus}...")
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    if df.empty:
        print("❌ No data found.")
        return

    df['report_date'] = pd.to_datetime(df['report_date'])
    
    for spu in spus:
        print(f"\nAnalyzing SPU: {spu}")
        # Filter for this SPU logic (need to apply the same substring logic or filter by joined data if possible, but here we fetched based on SQL SPU logic so just filter if mixed)
        # Actually the SQL already filters by SPU in ({in_list}), but the result doesn't have SPU column explicitly.
        # Let's re-apply SPU extraction in Python to be safe or just trust the query if we run one by one.
        # To be simple, let's just assume the returned rows are for the requested SPUs. Since we might have multiple, let's add SPU column in SQL or re-derive.
        # Let's re-derive for safety.
        def get_spu(sku):
            if sku.startswith('RHNWB'): return sku[5:9]
            if sku.startswith('VY'): return sku[4:8]
            if sku.startswith('WB'): return sku[2:6]
            return '-'
            
        df['spu_derived'] = df['local_sku'].apply(get_spu)
        spu_df = df[df['spu_derived'] == spu].copy()
        
        if spu_df.empty:
            print(f"  No data for {spu}")
            continue

        # Pivot to SKU columns, Weekly Resample
        pivot = spu_df.pivot_table(index='report_date', columns='local_sku', values='sales', aggfunc='sum').fillna(0)
        weekly = pivot.resample('W-MON').sum()
        
        # Calculate Shares
        spu_total = weekly.sum(axis=1)
        # Filter out weeks with very low total volume (noise)
        valid_weeks = spu_total > 5
        weekly_valid = weekly[valid_weeks]
        spu_total_valid = spu_total[valid_weeks]
        
        if len(weekly_valid) < 10:
            print("  Not enough valid weeks for trend analysis.")
            continue
            
        shares = weekly_valid.div(spu_total_valid, axis=0).fillna(0)
        
        # Analyze Trends (Slope)
        print(f"  {'SKU':<20} | {'Mean Share':<10} | {'Trend Slope (1e-4)':<18} | {'Status'}")
        print("-" * 65)
        
        trends = []
        
        # Prepare plot
        plt.figure(figsize=(12, 6))
        
        for sku in shares.columns:
            y = shares[sku].values
            X = np.arange(len(y)).reshape(-1, 1)
            
            # Linear Regression
            reg = LinearRegression().fit(X, y)
            slope = reg.coef_[0]
            mean_share = y.mean()
            
            # Filter out insignificant SKUs
            if mean_share < 0.02: continue
            
            status = "Stable"
            if slope > 0.0005: status = "↗️ Rising"
            elif slope < -0.0005: status = "↘️ Falling"
            
            print(f"  {sku:<20} | {mean_share:.2%}     | {slope*10000:.2f}               | {status}")
            
            if abs(slope) > 0.0005: # Only plot significant trends
                plt.plot(shares.index, y, label=f"{sku} ({status})")
                trends.append(sku)

        if trends:
            plt.title(f"SKU Share Trends for SPU {spu}")
            plt.ylabel("Share of SPU Total")
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            out_file = f"sku_trends_{spu}.png"
            plt.savefig(out_file)
            print(f"  📸 Plot saved to {out_file}")
        else:
            plt.close()
            print("  No significant trends detected.")

if __name__ == "__main__":
    db_url = os.getenv("SALES_FORECAST_DB_URL")
    # Test with SPU 0887 and maybe 0779
    analyze_trends(["0887", "0779"], db_url)
