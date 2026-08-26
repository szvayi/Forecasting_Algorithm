import json

import numpy as np
import pandas as pd


def _project_future_exog_series(series, horizon, seasonal_lag=13):
    clean = pd.Series(series).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return [0.0] * horizon

    if len(clean) < 4:
        fallback = float(clean.mean()) if len(clean) > 0 else 0.0
        return [fallback] * horizon

    recent_window = min(6, len(clean))
    recent = clean.iloc[-recent_window:]
    base_value = float(recent.mean())

    try:
        slope = float(np.polyfit(np.arange(len(recent)), recent.values, 1)[0]) if len(recent) >= 3 else 0.0
    except Exception:
        slope = 0.0

    seasonal_values = None
    if len(clean) >= seasonal_lag * 2:
        seasonal_values = clean.iloc[-seasonal_lag:].tolist()
    elif len(clean) >= 4:
        seasonal_values = clean.iloc[-4:].tolist()

    recent_min = float(recent.min())
    recent_max = float(recent.max())
    lower_bound = min(recent_min * 0.7, recent_max * 1.3, base_value)
    upper_bound = max(recent_min * 0.7, recent_max * 1.3, base_value)
    if abs(upper_bound - lower_bound) < 1e-9:
        upper_bound = lower_bound + 1.0

    forecast = []
    for step in range(horizon):
        trend_value = base_value + slope * (step + 1) * 0.6
        if seasonal_values:
            seasonal_value = float(seasonal_values[step % len(seasonal_values)])
            value = 0.65 * trend_value + 0.35 * seasonal_value
        else:
            value = trend_value

        clipped = float(np.clip(value, lower_bound, upper_bound))
        if base_value >= 0:
            clipped = max(0.0, clipped)
        forecast.append(clipped)

    return forecast


def build_future_exog_frame(exog_series, future_dates):
    if exog_series is None or len(exog_series) == 0:
        return None

    future_dates = pd.DatetimeIndex(future_dates)
    horizon = len(future_dates)
    if horizon == 0:
        return pd.DataFrame(index=future_dates)

    future_exog_data = {}
    for col in exog_series.columns:
        projected = _project_future_exog_series(exog_series[col], horizon)
        if not projected:
            non_null = exog_series[col].dropna()
            fallback = float(non_null.mean()) if not non_null.empty else 0.0
            projected = [fallback] * horizon
        future_exog_data[col] = projected

    return pd.DataFrame(future_exog_data, index=future_dates)


def _calculate_group_dynamic_shares(df_spu_idx, group_col, spu_sales_weekly, future_dates):
    grouped_sales = df_spu_idx.groupby([pd.Grouper(freq="W"), group_col])["sales"].sum().unstack(fill_value=0)
    grouped_sales = grouped_sales.reindex(spu_sales_weekly.index, fill_value=0)

    total = grouped_sales.sum(axis=1)
    hist_shares = grouped_sales.div(total.replace(0, np.nan), axis=0).ffill().fillna(0)

    future_shares = {}
    lookback_weeks = 12
    min_weeks = 4
    damping_factor = 0.9

    for sku in hist_shares.columns:
        series = hist_shares[sku]
        n = len(series)

        if n >= min_weeks:
            window_size = min(n, lookback_weeks)
            recent_data = series.iloc[-window_size:]
            current_level = recent_data.ewm(span=window_size, adjust=False).mean().iloc[-1]

            try:
                x = np.arange(window_size)
                y = recent_data.values
                slope, _ = np.polyfit(x, y, 1)
            except Exception:
                slope = 0.0

            future_vals = []
            curr_val = current_level
            curr_slope = slope

            for _ in range(len(future_dates)):
                curr_val += curr_slope
                curr_slope *= damping_factor
                curr_val = max(0.0001, min(1.0, curr_val))
                future_vals.append(curr_val)
            future_shares[sku] = future_vals
        else:
            mean_val = series.mean() if len(series) > 0 else 0
            future_shares[sku] = [mean_val] * len(future_dates)

    future_df = pd.DataFrame(future_shares, index=future_dates)
    row_sums = future_df.sum(axis=1)
    future_df = future_df.div(row_sums.replace(0, 1), axis=0).fillna(0)
    json_list = future_df.apply(lambda row: json.dumps(row.to_dict(), ensure_ascii=False), axis=1).values
    return json_list, future_df


def calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates):
    return _calculate_group_dynamic_shares(df_spu_idx, "sku", spu_sales_weekly, future_dates)


def calculate_principal_dynamic_shares(df_spu_idx, spu_sales_weekly, future_dates):
    if "principal_names" not in df_spu_idx.columns:
        df_spu_idx = df_spu_idx.copy()
        df_spu_idx["principal_names"] = "UNKNOWN"
    else:
        df_spu_idx = df_spu_idx.copy()
        df_spu_idx["principal_names"] = (
            df_spu_idx["principal_names"]
            .astype(str)
            .str.strip()
            .replace({"": "UNKNOWN", "nan": "UNKNOWN", "None": "UNKNOWN"})
        )
    return _calculate_group_dynamic_shares(df_spu_idx, "principal_names", spu_sales_weekly, future_dates)

