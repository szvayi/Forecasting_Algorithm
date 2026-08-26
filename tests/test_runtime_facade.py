import pandas as pd
import numpy as np


def test_runtime_facade_dynamic_share_helpers():
    from src.forecasting.runtime_facade import calculate_dynamic_shares, calculate_principal_dynamic_shares, build_future_exog_frame

    dates = pd.date_range("2025-01-01", periods=12, freq="W")
    df = pd.DataFrame(
        {
            "date": np.tile(dates, 2),
            "sku": ["SKU001", "SKU002"] * 12,
            "principal_names": ["P1", "P2"] * 12,
            "sales": np.random.randint(10, 100, 24),
        }
    ).set_index("date")
    weekly = pd.Series(np.random.randint(100, 200, len(dates)), index=dates)
    future_dates = pd.date_range("2025-04-01", periods=4, freq="W")

    sku_json_list, sku_df = calculate_dynamic_shares(df, "SPU001", weekly, future_dates)
    principal_json_list, principal_df = calculate_principal_dynamic_shares(df, weekly, future_dates)
    exog = build_future_exog_frame(pd.DataFrame({"ad_cost": weekly}), future_dates)

    assert len(sku_json_list) == len(future_dates)
    assert len(principal_json_list) == len(future_dates)
    assert isinstance(sku_df, pd.DataFrame)
    assert isinstance(principal_df, pd.DataFrame)
    assert isinstance(exog, pd.DataFrame)
