import os
import datetime
import json
import pandas as pd
from sqlalchemy import create_engine, text


def main():
    db_url = os.getenv("SALES_FORECAST_DB_URL")
    if not db_url:
        raise RuntimeError("缺少环境变量 SALES_FORECAST_DB_URL")

    today = datetime.date.today()
    future_dates = [today + datetime.timedelta(days=7 * i) for i in range(1, 5)]

    # 构造简单的演示数据（1 个 SPU，2 个 SKU）
    sku_share_json = json.dumps([
        {"date": future_dates[0].isoformat(), "shares": {"SKU_A": 0.7, "SKU_B": 0.3}},
        {"date": future_dates[1].isoformat(), "shares": {"SKU_A": 0.68, "SKU_B": 0.32}},
        {"date": future_dates[2].isoformat(), "shares": {"SKU_A": 0.66, "SKU_B": 0.34}},
        {"date": future_dates[3].isoformat(), "shares": {"SKU_A": 0.65, "SKU_B": 0.35}},
    ], ensure_ascii=False)

    sku_accuracy_json = json.dumps({
        "SKU_A": {"wmape": 0.12, "total_sales": 1000, "weight_in_spu": 0.8},
        "SKU_B": {"wmape": 0.22, "total_sales": 250, "weight_in_spu": 0.2},
    }, ensure_ascii=False)

    seasonal_factors_json = json.dumps({"period": 52, "factors": [1.0] * 52}, ensure_ascii=False)

    df = pd.DataFrame({
        "spu": ["DEMO_SPU"] * len(future_dates),
        "run_date": [today] * len(future_dates),
        "forecast_target_date": future_dates,
        "spu_forecast_value": [120.0, 130.0, 140.0, 150.0],
        "sku_share_json": [sku_share_json] * len(future_dates),
        "seasonal_factors_json": [seasonal_factors_json] * len(future_dates),
        "sku_accuracy_json": [sku_accuracy_json] * len(future_dates),
        "winner_algo": ["Demo_Model"] * len(future_dates),
        "validation_wmape": [0.15] * len(future_dates),
        "best_params": [json.dumps({"param": "value"}, ensure_ascii=False)] * len(future_dates),
        "has_exog_features": [False] * len(future_dates),
        "exog_columns": [None] * len(future_dates),
        "training_weeks": [52] * len(future_dates),
        "data_end_date": [today] * len(future_dates),
        "create_time": [datetime.datetime.now()] * len(future_dates),
    })

    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd AND spu = :spu")
            conn.execute(del_query, {"rd": str(today), "spu": "DEMO_SPU"})
            df.to_sql(
                "sales_forecast_history",
                con=conn,
                schema="finedatalink",
                if_exists="append",
                index=False,
                method="multi",
                chunksize=100,
            )
        print(f"✅ 写入完成: finedatalink.sales_forecast_history 记录数={len(df)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

