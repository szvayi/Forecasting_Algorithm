import os
import random
import logging
import json
import warnings
import traceback
import queue
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Dict, List
import pandas as pd
import numpy as np
from scipy import stats
from scipy.signal import find_peaks
from statsmodels.tsa.stattools import adfuller, acf

import matplotlib.pyplot as plt
from matplotlib import rcParams

rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False


logging.getLogger('prophet').setLevel(logging.ERROR)
logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

DEBUG_MODE = False
PROPHET_VALID_PARAMS = {
    'changepoint_prior_scale', 'seasonality_prior_scale',
    'seasonality_mode', 'changepoint_range', 'n_changepoints',
}

@dataclass
class SPUProfile:
    spu: str
    data_length: int
    data_start: pd.Timestamp
    data_end: pd.Timestamp
    avg_sales: float
    std_sales: float
    cv: float
    trend: str
    seasonality: bool
    has_exog: bool
    winner_algo: str = ""
    winner_wmape: float = float('inf')
    total_time: float = 0.0
    forecast_values: List[float] = field(default_factory=list)

class SPUProfiler:
    def __init__(self, verbose=False):
        self.verbose = verbose

    def analyze(self, spu, series, original_series, exog_series):
        data_length = len(series)
        data_start = series.index.min()
        data_end = series.index.max()
        avg_sales = float(series.mean())
        std_sales = float(series.std())
        cv = std_sales / avg_sales if avg_sales > 0 else 0

        trend = self._detect_trend(series)
        seasonality = self._detect_seasonality(series)
        has_exog = exog_series is not None and len(exog_series) > 0

        return SPUProfile(
            spu=spu,
            data_length=data_length,
            data_start=data_start,
            data_end=data_end,
            avg_sales=avg_sales,
            std_sales=std_sales,
            cv=cv,
            trend=trend,
            seasonality=seasonality,
            has_exog=has_exog
        )

    def _detect_trend(self, series):
        if len(series) < 10:
            return "insufficient_data"
        try:
            slope, _ = np.polyfit(range(len(series)), series.values, 1)
            if abs(slope) < 0.01 * series.mean():
                return "flat"
            return "up" if slope > 0 else "down"
        except:
            return "unstable"

    def _detect_seasonality(self, series):
        if len(series) < 12:
            return False
        try:
            acf_vals = acf(series, nlags=12)
            return any(abs(val) > 0.3 for val in acf_vals[1:])
        except:
            return False

    def update_with_results(self, profile, train, test, all_results, winner, forecast_values, total_time):
        profile.winner_algo = winner['name']
        profile.winner_wmape = winner['wmape']
        profile.total_time = total_time
        profile.forecast_values = forecast_values
        return profile

    def print_profile(self, profile):
        if not self.verbose:
            return
        print(f"   📊 SPU 概览: {profile.spu}")
        print(f"   ├─ 数据长度: {profile.data_length} 周")
        print(f"   ├─ 时间范围: {profile.data_start.strftime('%Y-%m-%d')} 至 {profile.data_end.strftime('%Y-%m-%d')}")
        print(f"   ├─ 平均销量: {profile.avg_sales:.2f}")
        print(f"   ├─ 标准差: {profile.std_sales:.2f}")
        print(f"   ├─ 变异系数: {profile.cv:.3f}")
        print(f"   ├─ 趋势: {profile.trend}")
        print(f"   ├─ 季节性: {'存在' if profile.seasonality else '无'}")
        print(f"   └─ 外生变量: {'使用' if profile.has_exog else '无'}")

    def print_model_competition(self, profile):
        if not self.verbose:
            return
        print(f"   🏆 胜出模型: {profile.winner_algo} (WMAPE: {profile.winner_wmape:.2%})")

    def print_forecast_summary(self, profile, future_dates, forecast_values):
        if not self.verbose:
            return
        print(f"   📈 预测摘要:")
        print(f"   ├─ 预测周期: {len(forecast_values)} 周")
        print(f"   ├─ 平均预测: {np.mean(forecast_values):.2f}")
        print(f"   ├─ 预测开始: {future_dates[0].strftime('%Y-%m-%d')}")
        print(f"   └─ 预测结束: {future_dates[-1].strftime('%Y-%m-%d')}")

    def generate_report_dict(self, profile):
        return {
            'spu': profile.spu,
            'data_length': profile.data_length,
            'data_start': profile.data_start.strftime('%Y-%m-%d'),
            'data_end': profile.data_end.strftime('%Y-%m-%d'),
            'avg_sales': profile.avg_sales,
            'std_sales': profile.std_sales,
            'cv': profile.cv,
            'trend': profile.trend,
            'seasonality': profile.seasonality,
            'has_exog': profile.has_exog,
            'winner_algo': profile.winner_algo,
            'winner_wmape': profile.winner_wmape,
            'total_time': profile.total_time,
            'forecast_values': profile.forecast_values
        }

class FeatureEngineer:
    def __init__(self, lags=None, rolling_windows=None):
        self.lags = lags or [1, 2, 4]
        self.rolling_windows = rolling_windows or [4, 8]
        self.extra_lags = [8, 13, 26, 52]
        self.extra_windows = [13, 26, 52]
        self.exog_windows = [4, 8]
        self.feature_names, self.has_exog, self.exog_cols = None, False, []
        self._is_fitted, self._exog_means = False, {}

    def make_features(self, data_series, exog_df=None):
        df = pd.DataFrame(data_series.copy()); df.columns = ['y']; df['time_idx'] = np.arange(len(df))
        for lag in self.lags: df[f'lag_{lag}'] = df['y'].shift(lag)
        for w in self.rolling_windows:
            df[f'roll_mean_{w}'] = df['y'].shift(1).rolling(w).mean()
            df[f'roll_std_{w}'] = df['y'].shift(1).rolling(w).std()
        if exog_df is not None and len(exog_df) > 0:
            self.has_exog, self.exog_cols = True, list(exog_df.columns)
            exog_aligned = exog_df.reindex(df.index)
            for col in self.exog_cols:
                col_values = exog_aligned[col].fillna(0).values
                df[col] = col_values
                df[f'{col}_lag1'] = pd.Series(col_values, index=df.index).shift(1).fillna(0).values
                self._exog_means[col] = float(np.nanmean(col_values))
        
        # 保存所有可能的特征名称，即使df.dropna()后为空
        all_feature_names = [c for c in df.columns if c != 'y']
        
        df = df.dropna()
        
        # 如果df为空，使用所有可能的特征名称
        if len(df) == 0:
            self.feature_names = all_feature_names
        else:
            self.feature_names = [c for c in df.columns if c != 'y']
        
        self._is_fitted = True
        return df.drop('y', axis=1), df['y']

    def make_features_for_prediction(self, data_series, exog_df=None):
        if not self._is_fitted: return self.make_features(data_series, exog_df)
        df = pd.DataFrame(data_series.copy()); df.columns = ['y']; df['time_idx'] = np.arange(len(df))
        for lag in self.lags: df[f'lag_{lag}'] = df['y'].shift(lag)
        for w in self.rolling_windows:
            df[f'roll_mean_{w}'] = df['y'].shift(1).rolling(w).mean()
            df[f'roll_std_{w}'] = df['y'].shift(1).rolling(w).std()
        if self.has_exog:
            if exog_df is not None and len(exog_df) > 0:
                exog_aligned = exog_df.reindex(df.index)
                for col in self.exog_cols:
                    col_vals = exog_aligned[col].fillna(self._exog_means.get(col, 0)).values if col in exog_aligned.columns else np.full(len(df), self._exog_means.get(col, 0))
                    df[col] = col_vals
                    df[f'{col}_lag1'] = pd.Series(col_vals, index=df.index).shift(1).fillna(col_vals[0] if len(col_vals)>0 else 0).values
            else:
                for col in self.exog_cols: df[col], df[f'{col}_lag1'] = self._exog_means.get(col, 0), self._exog_means.get(col, 0)
        
        # 对于预测，不删除NaN值，而是填充它们
        # 填充滞后项和滚动窗口的NaN值
        for col in df.columns:
            if col != 'y' and df[col].isna().any():
                # 对于时间索引，直接使用0
                if col == 'time_idx':
                    df[col] = df[col].fillna(0)
                # 对于其他特征，使用0填充
                else:
                    df[col] = df[col].fillna(0)
        
        # 确保self.feature_names不为None
        if self.feature_names:
            for col in self.feature_names:
                if col not in df.columns: df[col] = 0
            return df[self.feature_names], df['y']
        else:
            # 如果self.feature_names为None，返回所有特征
            return df.drop('y', axis=1), df['y']

    def make_single_row(self, history, current_time_idx, exog_current=None, exog_lag1=None):
        feat = {'time_idx': float(current_time_idx)}
        history = list(history.values.tolist() if hasattr(history, 'values') else history)
        for lag in self.lags: feat[f'lag_{lag}'] = float(history[-lag]) if len(history) >= lag else float(np.mean(history) if history else 0)
        for w in self.rolling_windows:
            if len(history) >= w:
                feat[f'roll_mean_{w}'], feat[f'roll_std_{w}'] = float(np.mean(history[-w:])), float(np.std(history[-w:])) if w>1 else 0.0
            else:
                feat[f'roll_mean_{w}'], feat[f'roll_std_{w}'] = float(np.mean(history) if history else 0), float(np.std(history)) if len(history)>1 else 0.0
        if self.has_exog:
            for col in self.exog_cols:
                feat[col] = float(exog_current[col]) if exog_current and col in exog_current else self._exog_means.get(col, 0.0)
                feat[f'{col}_lag1'] = float(exog_lag1[col]) if exog_lag1 and col in exog_lag1 else feat[col]
        row = pd.DataFrame([feat])
        if self.feature_names:
            for col in self.feature_names:
                if col not in row.columns: row[col] = 0.0
            row = row[self.feature_names]
        return row

    def copy(self):
        new_eng = FeatureEngineer(lags=self.lags.copy(), rolling_windows=self.rolling_windows.copy())
        new_eng.feature_names = self.feature_names.copy() if self.feature_names else None
        new_eng.has_exog, new_eng.exog_cols = self.has_exog, self.exog_cols.copy() if self.exog_cols else []
        new_eng._is_fitted, new_eng._exog_means = self._is_fitted, self._exog_means.copy()
        return new_eng


class FeatureEngineer:
    def __init__(self, lags=None, rolling_windows=None):
        self.lags = lags or [1, 2, 4]
        self.rolling_windows = rolling_windows or [4, 8]
        self.extra_lags = [8, 13, 26, 52]
        self.extra_windows = [13, 26, 52]
        self.exog_windows = [4, 8]
        self.feature_names, self.has_exog, self.exog_cols = None, False, []
        self._is_fitted, self._exog_means = False, {}

    def _get_enabled_lags(self, history_length):
        enabled = list(self.lags)
        for lag in self.extra_lags:
            if history_length >= lag + 2 and lag not in enabled:
                enabled.append(lag)
        return sorted(enabled)

    def _get_enabled_windows(self, history_length):
        enabled = list(self.rolling_windows)
        for window in self.extra_windows:
            if history_length >= window + 2 and window not in enabled:
                enabled.append(window)
        return sorted(enabled)

    def _build_time_features(self, df):
        time_idx = df['time_idx'].astype(float)
        denom = max(len(df) - 1, 1)
        df['time_idx_norm'] = time_idx / denom
        df['time_idx_sq'] = df['time_idx_norm'] ** 2
        for period in (13, 26, 52):
            df[f'time_sin_{period}'] = np.sin(2 * np.pi * time_idx / period)
            df[f'time_cos_{period}'] = np.cos(2 * np.pi * time_idx / period)

    def _build_history_features(self, df):
        history_length = len(df)
        for lag in self._get_enabled_lags(history_length):
            df[f'lag_{lag}'] = df['y'].shift(lag)

        shifted = df['y'].shift(1)
        for window in self._get_enabled_windows(history_length):
            rolling = shifted.rolling(window)
            df[f'roll_mean_{window}'] = rolling.mean()
            df[f'roll_std_{window}'] = rolling.std()
            if window >= 13:
                df[f'roll_min_{window}'] = rolling.min()
                df[f'roll_max_{window}'] = rolling.max()

        if history_length >= 5:
            df['momentum_1_4'] = df['y'].shift(1) - df['y'].shift(4)
            df['ewm_mean_4'] = shifted.ewm(span=4, adjust=False).mean()
        if history_length >= 9:
            df['ewm_mean_8'] = shifted.ewm(span=8, adjust=False).mean()
        if history_length >= 14:
            df['momentum_4_13'] = df['y'].shift(4) - df['y'].shift(13)
            df['ewm_mean_13'] = shifted.ewm(span=13, adjust=False).mean()
        df['pct_change_1'] = shifted.replace(0, np.nan).pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)

    def _build_exog_features(self, df, exog_df):
        if exog_df is None or len(exog_df) == 0:
            if self.has_exog:
                for col in self.exog_cols:
                    default = self._exog_means.get(col, 0.0)
                    df[col] = default
                    df[f'{col}_lag1'] = default
            return

        self.has_exog = True
        self.exog_cols = list(exog_df.columns)
        exog_aligned = exog_df.reindex(df.index)
        for col in self.exog_cols:
            filled = exog_aligned[col].astype(float).replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(0.0)
            self._exog_means[col] = float(filled.mean()) if len(filled) > 0 else 0.0
            df[col] = filled.values
            df[f'{col}_lag1'] = filled.shift(1)
            for lag in (4, 13):
                if len(df) >= lag + 2:
                    df[f'{col}_lag{lag}'] = filled.shift(lag)
            for window in self.exog_windows:
                if len(df) >= window + 2:
                    df[f'{col}_roll_mean_{window}'] = filled.shift(1).rolling(window).mean()
            df[f'{col}_delta_1'] = filled - filled.shift(1)
            df[f'{col}_pct_change_1'] = filled.replace(0, np.nan).pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)

        # Business interactions: pricing + ads coupling and rough elasticity proxy.
        if "price" in self.exog_cols and "ad_cost" in self.exog_cols:
            price = exog_aligned["price"].astype(float).replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(0.0)
            ad_cost = exog_aligned["ad_cost"].astype(float).replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(0.0)
            df["price_ad_interaction"] = price * ad_cost
            df["ad_cost_per_price"] = ad_cost / np.maximum(price, 1e-6)
            sales_shift = df["y"].shift(1).replace([np.inf, -np.inf], np.nan)
            df["price_elasticity_proxy"] = (
                sales_shift.replace(0, np.nan).pct_change(fill_method=None)
                / price.replace(0, np.nan).pct_change(fill_method=None)
            ).replace([np.inf, -np.inf], np.nan)

    def _build_frame(self, data_series, exog_df=None, for_prediction=False):
        df = pd.DataFrame(data_series.copy())
        df.columns = ['y']
        df['time_idx'] = np.arange(len(df), dtype=float)
        self._build_time_features(df)
        self._build_history_features(df)
        self._build_exog_features(df, exog_df)
        df = df.replace([np.inf, -np.inf], np.nan)
        all_feature_names = [c for c in df.columns if c != 'y']
        if for_prediction:
            df = df.ffill().bfill().fillna(0.0)
        else:
            df = df.dropna()
        if not for_prediction or self.feature_names is None:
            if len(df) == 0:
                self.feature_names = all_feature_names
            else:
                self.feature_names = [c for c in df.columns if c != 'y']
        return df

    def make_features(self, data_series, exog_df=None):
        df = self._build_frame(data_series, exog_df=exog_df, for_prediction=False)
        self._is_fitted = True
        return df.drop('y', axis=1), df['y']

    def make_features_for_prediction(self, data_series, exog_df=None):
        if not self._is_fitted:
            return self.make_features(data_series, exog_df)

        df = self._build_frame(data_series, exog_df=exog_df, for_prediction=True)
        if self.feature_names:
            for col in self.feature_names:
                if col not in df.columns:
                    df[col] = 0.0
            return df[self.feature_names], df['y']
        return df.drop('y', axis=1), df['y']

    def make_single_row(self, history, current_time_idx, exog_current=None, exog_lag1=None, exog_history_map=None):
        feat = {'time_idx': float(current_time_idx)}
        history = list(history.values.tolist() if hasattr(history, 'values') else history)
        history_length = len(history)
        history_array = np.array(history, dtype=float) if history else np.array([0.0])
        time_norm = float(current_time_idx) / max(float(current_time_idx) + 1.0, 1.0)
        feat['time_idx_norm'] = time_norm
        feat['time_idx_sq'] = time_norm ** 2
        for period in (13, 26, 52):
            feat[f'time_sin_{period}'] = float(np.sin(2 * np.pi * current_time_idx / period))
            feat[f'time_cos_{period}'] = float(np.cos(2 * np.pi * current_time_idx / period))

        for lag in self._get_enabled_lags(history_length):
            feat[f'lag_{lag}'] = float(history_array[-lag]) if len(history_array) >= lag else float(np.mean(history_array))
        for window in self._get_enabled_windows(history_length):
            window_values = history_array[-window:] if len(history_array) >= window else history_array
            feat[f'roll_mean_{window}'] = float(np.mean(window_values))
            feat[f'roll_std_{window}'] = float(np.std(window_values)) if len(window_values) > 1 else 0.0
            if window >= 13:
                feat[f'roll_min_{window}'] = float(np.min(window_values))
                feat[f'roll_max_{window}'] = float(np.max(window_values))

        if len(history_array) >= 4:
            feat['momentum_1_4'] = float(history_array[-1] - history_array[-4])
            feat['ewm_mean_4'] = float(pd.Series(history_array).ewm(span=4, adjust=False).mean().iloc[-1])
        if len(history_array) >= 8:
            feat['ewm_mean_8'] = float(pd.Series(history_array).ewm(span=8, adjust=False).mean().iloc[-1])
        if len(history_array) >= 13:
            feat['momentum_4_13'] = float(history_array[-4] - history_array[-13])
            feat['ewm_mean_13'] = float(pd.Series(history_array).ewm(span=13, adjust=False).mean().iloc[-1])
        if len(history_array) >= 2 and history_array[-2] != 0:
            feat['pct_change_1'] = float((history_array[-1] - history_array[-2]) / history_array[-2])
        else:
            feat['pct_change_1'] = 0.0

        if self.has_exog:
            for col in self.exog_cols:
                exog_history = list(exog_history_map.get(col, [])) if exog_history_map else []
                current_value = float(exog_current[col]) if exog_current and col in exog_current else (float(exog_history[-1]) if exog_history else self._exog_means.get(col, 0.0))
                feat[col] = current_value
                feat[f'{col}_lag1'] = float(exog_lag1[col]) if exog_lag1 and col in exog_lag1 else (float(exog_history[-2]) if len(exog_history) >= 2 else current_value)
                for lag in (4, 13):
                    if f'{col}_lag{lag}' in (self.feature_names or []):
                        feat[f'{col}_lag{lag}'] = float(exog_history[-lag]) if len(exog_history) >= lag else current_value
                for window in self.exog_windows:
                    key = f'{col}_roll_mean_{window}'
                    if key in (self.feature_names or []):
                        values = np.array(exog_history[-window:] if len(exog_history) >= window else exog_history or [current_value], dtype=float)
                        feat[key] = float(np.mean(values))
                prev_value = feat.get(f'{col}_lag1', current_value)
                feat[f'{col}_delta_1'] = float(current_value - prev_value)
                feat[f'{col}_pct_change_1'] = float((current_value - prev_value) / prev_value) if prev_value not in (0, 0.0) else 0.0

            if "price" in self.exog_cols and "ad_cost" in self.exog_cols:
                price_val = float(feat.get("price", self._exog_means.get("price", 0.0)))
                ad_val = float(feat.get("ad_cost", self._exog_means.get("ad_cost", 0.0)))
                feat["price_ad_interaction"] = float(price_val * ad_val)
                feat["ad_cost_per_price"] = float(ad_val / max(price_val, 1e-6))
                # Online inference proxy: use last observed sales momentum over price momentum.
                if len(history_array) >= 2 and history_array[-2] != 0:
                    sales_change = float((history_array[-1] - history_array[-2]) / history_array[-2])
                else:
                    sales_change = 0.0
                price_prev = float(feat.get("price_lag1", price_val))
                price_change = float((price_val - price_prev) / price_prev) if price_prev not in (0, 0.0) else 0.0
                feat["price_elasticity_proxy"] = float(sales_change / price_change) if abs(price_change) > 1e-9 else 0.0

        row = pd.DataFrame([feat]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if self.feature_names:
            for col in self.feature_names:
                if col not in row.columns:
                    row[col] = 0.0
            row = row[self.feature_names]
        return row

    def copy(self):
        new_eng = FeatureEngineer(lags=self.lags.copy(), rolling_windows=self.rolling_windows.copy())
        new_eng.feature_names = self.feature_names.copy() if self.feature_names else None
        new_eng.has_exog = self.has_exog
        new_eng.exog_cols = self.exog_cols.copy() if self.exog_cols else []
        new_eng._is_fitted = self._is_fitted
        new_eng._exog_means = self._exog_means.copy()
        return new_eng
