import numpy as np
import pandas as pd

from config_and_utils import build_future_exog_frame
from src.forecasting.models import FeatureEngineer


def test_feature_engineer_preserves_base_and_adds_enhanced_features():
    index = pd.date_range("2024-01-07", periods=80, freq="W")
    series = pd.Series(np.linspace(100, 180, 80) + 10 * np.sin(np.arange(80) / 4), index=index)
    exog = pd.DataFrame(
        {
            "price": np.linspace(20, 24, 80),
            "ad_cost": np.linspace(100, 140, 80),
        },
        index=index,
    )

    engineer = FeatureEngineer()
    x_train, y_train = engineer.make_features(series, exog)

    assert not x_train.empty
    assert len(x_train) == len(y_train)
    assert "time_idx" in x_train.columns
    assert "lag_1" in x_train.columns
    assert "roll_mean_4" in x_train.columns
    assert "time_sin_13" in x_train.columns
    assert "lag_13" in x_train.columns
    assert "roll_mean_13" in x_train.columns
    assert "momentum_1_4" in x_train.columns
    assert "price_lag1" in x_train.columns
    assert "price_roll_mean_4" in x_train.columns
    assert "ad_cost_delta_1" in x_train.columns


def test_feature_engineer_prediction_alignment_for_short_history():
    index = pd.date_range("2025-01-05", periods=12, freq="W")
    series = pd.Series(np.arange(12, dtype=float) + 50, index=index)

    engineer = FeatureEngineer()
    x_train, _ = engineer.make_features(series)
    future_index = pd.date_range(index[-1] + pd.Timedelta(weeks=1), periods=4, freq="W")
    x_future, _ = engineer.make_features_for_prediction(pd.Series([0.0, 0.0, 0.0, 0.0], index=future_index))

    assert not x_train.empty
    assert list(x_future.columns) == list(engineer.feature_names)
    assert "lag_1" in x_future.columns
    assert "roll_mean_4" in x_future.columns
    assert x_future.isna().sum().sum() == 0


def test_build_future_exog_frame_uses_bounded_projection_and_fallback():
    index = pd.date_range("2024-01-07", periods=20, freq="W")
    exog = pd.DataFrame(
        {
            "price": np.linspace(20, 30, 20),
            "ad_cost": [np.nan] * 3 + list(np.linspace(100, 118, 17)),
        },
        index=index,
    )
    future_dates = pd.date_range(index[-1] + pd.Timedelta(weeks=1), periods=6, freq="W")

    future_exog = build_future_exog_frame(exog, future_dates)

    assert future_exog is not None
    assert list(future_exog.index) == list(future_dates)
    assert list(future_exog.columns) == ["price", "ad_cost"]
    assert future_exog.isna().sum().sum() == 0
    assert (future_exog["price"] >= 0).all()
    assert (future_exog["ad_cost"] >= 0).all()
