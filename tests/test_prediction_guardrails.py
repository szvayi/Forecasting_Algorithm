import math

import numpy as np
import pandas as pd

from src.forecasting.sample_screening import screen_weekly_series
from src.forecasting.predictors import calculate_wmape, safe_predictions


def test_calculate_wmape_caps_when_non_zero_points_too_sparse():
    y_true = np.array([0, 0, 5, 0, 0, 3])
    y_pred = np.array([1, 2, 4, 1, 1, 2])

    wmape = calculate_wmape(y_true, y_pred, min_non_zero_points=4)

    assert wmape == 9.999


def test_safe_predictions_caps_extreme_positive_forecasts_against_recent_history():
    history = pd.Series([8, 9, 10, 11, 12, 10, 9, 11, 10, 12, 13, 12], dtype=float)
    preds = np.array([15.0, 18.0, 220.0, 260.0])

    guarded = safe_predictions(preds, fallback_value=10.0, model_name="XGBoost", history_series=history)

    assert guarded.max() <= 35.0
    assert guarded.max() < preds.max()
    assert list(guarded[:2]) == [15.0, 18.0]


def test_safe_predictions_replaces_nan_before_capping():
    history = pd.Series([4, 5, 6, 5, 4, 6, 5, 5, 6, 4, 5, 6], dtype=float)
    preds = np.array([np.nan, -3.0, 50.0])

    guarded = safe_predictions(preds, fallback_value=5.0, model_name="Prophet", history_series=history)

    assert guarded[0] == 5.0
    assert guarded[1] == 0.0
    assert guarded[2] <= 12.0


def test_screen_weekly_series_flags_156_week_zero_tail_anomaly():
    stable = [20.0] * 152
    tail = [0.0, 0.0, 0.0, 0.0]
    series = pd.Series(stable + tail, dtype=float)

    screening = screen_weekly_series(series)

    assert screening["history_weeks"] == 156
    assert screening["qualified_156_weeks"] is True
    assert screening["has_recent_zero_tail"] is True
    assert screening["is_anomalous"] is True
    assert screening["recommendation"] == "conservative"
    assert "recent_zero_tail" in screening["reasons"]


def test_screen_weekly_series_keeps_stable_156_week_sample_on_standard_path():
    series = pd.Series([18.0 + (i % 5) for i in range(156)], dtype=float)

    screening = screen_weekly_series(series)

    assert screening["history_weeks"] == 156
    assert screening["qualified_156_weeks"] is True
    assert screening["is_anomalous"] is False
    assert screening["recommendation"] == "standard"


def test_screen_weekly_series_uses_dynamic_collapse_ratio_for_sparse_history():
    # Sparse + short history should use stricter collapse threshold to avoid false standard.
    series = pd.Series([20.0] * 40 + [3.0] * 8, dtype=float)
    screening = screen_weekly_series(series, min_history_weeks=32, collapse_ratio=0.35)

    assert screening["history_weeks"] == 48
    assert screening["collapse_ratio_used"] >= 0.40
    assert screening["recommendation"] in {"conservative", "zero_override"}
