import os
os.environ['STAN_BACKEND'] = 'CMDSTANPY'
os.environ['CMDSTANPY_COMPILE'] = 'false'

import pandas as pd
import numpy as np
import pmdarima as pm
from prophet import Prophet
from statsmodels.tsa.arima.model import ARIMA as SMARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sklearn.preprocessing import MinMaxScaler
from sklearn.linear_model import Ridge
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import LSTM, Dense, Input, Conv1D, Flatten, Dropout, Lambda, Add
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping
import tensorflow as tf
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
import itertools
import time
import random
from functools import partial, lru_cache
from config_and_utils import *

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
        enabled_lags = self._get_enabled_lags(history_length)
        enabled_windows = self._get_enabled_windows(history_length)

        for lag in enabled_lags:
            df[f'lag_{lag}'] = df['y'].shift(lag)

        shifted = df['y'].shift(1)
        for window in enabled_windows:
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
        time_norm = float(current_time_idx) / max(float(current_time_idx) + 1.0, 1.0)
        feat['time_idx_norm'] = time_norm
        feat['time_idx_sq'] = time_norm ** 2
        for period in (13, 26, 52):
            feat[f'time_sin_{period}'] = float(np.sin(2 * np.pi * current_time_idx / period))
            feat[f'time_cos_{period}'] = float(np.cos(2 * np.pi * current_time_idx / period))

        enabled_lags = self._get_enabled_lags(history_length)
        enabled_windows = self._get_enabled_windows(history_length)
        history_array = np.array(history, dtype=float) if history else np.array([0.0])

        for lag in enabled_lags:
            feat[f'lag_{lag}'] = float(history_array[-lag]) if len(history_array) >= lag else float(np.mean(history_array))

        for window in enabled_windows:
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
        new_eng.has_exog, new_eng.exog_cols = self.has_exog, self.exog_cols.copy() if self.exog_cols else []
        new_eng._is_fitted, new_eng._exog_means = self._is_fitted, self._exog_means.copy()
        return new_eng

def tree_recursive_predict(model, history_diff, last_log_val, n_steps, feat_eng, start_idx, future_exog=None, exog_history=None):
    history = list(history_diff.values.flatten()) if hasattr(history_diff, 'values') else list(history_diff)
    preds_diff, curr_idx = [], start_idx
    exog_hist_dict, fut_exog_dict = {}, {}
    
    if feat_eng.has_exog:
        if exog_history is not None:
            for col in feat_eng.exog_cols: exog_hist_dict[col] = exog_history[col].tolist() if col in exog_history.columns else [feat_eng._exog_means.get(col, 0)]*len(exog_history)
        if future_exog is not None:
            for col in feat_eng.exog_cols: fut_exog_dict[col] = future_exog[col].tolist() if col in future_exog.columns else [feat_eng._exog_means.get(col, 0)]*len(future_exog)

    for i in range(n_steps):
        e_curr, e_lag1 = {}, {}
        if feat_eng.has_exog:
            for col in feat_eng.exog_cols:
                e_curr[col] = fut_exog_dict[col][i] if col in fut_exog_dict and i < len(fut_exog_dict[col]) else feat_eng._exog_means.get(col, 0)
                if i == 0: e_lag1[col] = exog_hist_dict[col][-1] if col in exog_hist_dict and len(exog_hist_dict[col])>0 else e_curr[col]
                else: e_lag1[col] = fut_exog_dict[col][i-1] if col in fut_exog_dict and (i-1)<len(fut_exog_dict[col]) else e_curr[col]
        exog_history_map = {}
        if feat_eng.has_exog:
            for col in feat_eng.exog_cols:
                hist_values = list(exog_hist_dict.get(col, []))
                future_values = list(fut_exog_dict.get(col, []))
                if i < len(future_values):
                    exog_history_map[col] = hist_values + future_values[:i+1]
                else:
                    exog_history_map[col] = hist_values or [feat_eng._exog_means.get(col, 0)]
        try:
            pred = float(model.predict(feat_eng.make_single_row(history, curr_idx, e_curr, e_lag1, exog_history_map))[0])
            pred = 0.0 if np.isnan(pred) or np.isinf(pred) else pred
        except: pred = 0.0
        preds_diff.append(pred); history.append(pred); curr_idx += 1

    return np.maximum(reconstruct_from_log_diff(last_log_val, np.array(preds_diff)), 0)

def optimize_tree_model(model_type, train_data, test_data, feat_eng, mode='full', train_exog=None, test_exog=None):
    best = {'name': {'xgboost': 'XGBoost', 'lgbm': 'LightGBM', 'catboost': 'CatBoost'}[model_type], 'wmape': float('inf'), 'forecast': None, 'params': None, 'error': None}
    try:
        train_diff, train_last_log = make_log_diff(train_data)
        train_exog_aligned = train_exog.iloc[1:].copy().set_index(train_diff.index) if train_exog is not None and len(train_exog)>0 else None
        X_train, y_train = feat_eng.make_features(train_diff, train_exog_aligned)
        if len(X_train) < 5: return best
        
        cfg = SearchConfig.get(mode).get(model_type, {})
        max_comb = SearchConfig.get(mode).get('max_combinations', 20)
        grid_params = {k: v for k, v in cfg.items() if isinstance(v, list)}
        all_combinations = [dict(zip(grid_params.keys(), v)) for v in itertools.product(*grid_params.values())] if grid_params else []
        combinations = random.sample(all_combinations, max_comb) if len(all_combinations) > max_comb else all_combinations
        
        test_values = test_data.values.flatten()
        test_exog_pred = test_exog.copy() if test_exog is not None else None
        
        # 【修复处】
        CatBoostRegressor = get_catboost_regressor()
        if model_type == 'catboost' and not CatBoostRegressor: return best
        
        for p in combinations:
            try:
                if model_type == 'xgboost': m = XGBRegressor(**p, objective='reg:squarederror', n_jobs=-1, random_state=42)
                elif model_type == 'lgbm': m = LGBMRegressor(**p, n_jobs=-1, random_state=42, verbose=-1)
                else: m = CatBoostRegressor(**{k: v for k, v in p.items() if k != 'colsample_bytree'}, loss_function='MAE', verbose=0, random_state=42)
                
                m.fit(X_train, y_train)
                pred = tree_recursive_predict(m, train_diff, train_last_log, len(test_values), feat_eng, X_train['time_idx'].iloc[-1]+1, test_exog_pred, train_exog_aligned)
                wmape = calculate_wmape(test_values, pred)
                
                if wmape < best['wmape']:
                    best.update({'wmape': wmape, 'forecast': pred, 'params': {**p, 'feat_eng': feat_eng.copy(), 'train_last_log': train_last_log, 'model_type': model_type}, 'error': None})
            except Exception as e:
                if best['error'] is None:
                    best['error'] = f"{model_type}: {str(e)[:50]}"
                continue
    except Exception as e: 
        best['error'] = str(e)
    return best

def optimize_prophet(train_data, test_data, mode='full', train_exog=None, test_exog=None):
    best = {'name': 'Prophet', 'wmape': float('inf'), 'forecast': None, 'params': None, 'error': None}
    ok, reason = prophet_backend_available()
    if not ok:
        # 回退：当 Prophet backend 异常时，使用 ETS 生成可用预测，避免算法位失效
        try:
            y = train_data.astype(float)
            test_values = test_data.values.flatten()
            seasonal_periods = 52 if len(y) >= 104 else 13 if len(y) >= 26 else None
            if seasonal_periods:
                model = ExponentialSmoothing(
                    y,
                    trend="add",
                    seasonal="add",
                    seasonal_periods=seasonal_periods,
                    initialization_method="estimated",
                )
            else:
                model = ExponentialSmoothing(
                    y,
                    trend="add",
                    seasonal=None,
                    initialization_method="estimated",
                )
            fit = model.fit(optimized=True, use_brute=False)
            pred = np.maximum(fit.forecast(len(test_values)).values, 0)
            wmape = calculate_wmape(test_values, pred)
            best.update(
                {
                    "name": "Prophet_Fallback",
                    "wmape": wmape,
                    "forecast": pred,
                    "params": {
                        "fallback": "ExponentialSmoothing",
                        "seasonal_periods": seasonal_periods,
                        "prophet_backend_error": str(reason)[:200],
                    },
                    "error": None,
                }
            )
            return best
        except Exception as e:
            best["error"] = f"Prophet backend unavailable: {reason}; fallback failed: {str(e)[:80]}"
            return best
    try:
        df_train = train_data.reset_index(); df_train.columns = ['ds', 'y']; df_train['ds'] = pd.to_datetime(df_train['ds'])
        exog_cols = []
        if train_exog is not None and len(train_exog)>0:
            exog_reset = train_exog.reset_index(); exog_reset.columns = ['ds'] + list(train_exog.columns)
            exog_reset['ds'] = pd.to_datetime(exog_reset['ds'])
            df_train = df_train.merge(exog_reset, on='ds', how='left')
            exog_cols = list(train_exog.columns)
            for col in exog_cols: df_train[col] = df_train[col].fillna(df_train[col].mean())
            
        test_values = test_data.values.flatten()
        cfg = SearchConfig.get(mode)['prophet']
        max_comb = SearchConfig.get(mode).get('max_combinations', 20)
        grid_params = {k: v for k, v in cfg.items() if isinstance(v, list)}
        all_combinations = [dict(zip(grid_params.keys(), v)) for v in itertools.product(*grid_params.values())]
        combinations = random.sample(all_combinations, max_comb) if len(all_combinations) > max_comb else all_combinations
        
        for p in combinations:
            try:
                valid_p = {k: v for k, v in p.items() if k in PROPHET_VALID_PARAMS}
                m = Prophet(**valid_p, yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False, uncertainty_samples=0)
                for col in exog_cols: m.add_regressor(col)
                with suppress_stdout_stderr(): m.fit(df_train)
                
                future = m.make_future_dataframe(periods=len(test_values), freq='W')
                if exog_cols and test_exog is not None:
                    full_exog = pd.concat([train_exog, test_exog]).reset_index()
                    full_exog.columns = ['ds'] + exog_cols; full_exog['ds'] = pd.to_datetime(full_exog['ds'])
                    future = future.merge(full_exog, on='ds', how='left')
                    for col in exog_cols: future[col] = future[col].fillna(future[col].mean())
                
                pred = np.maximum(m.predict(future)['yhat'].iloc[-len(test_values):].values, 0)
                wmape = calculate_wmape(test_values, pred)
                if wmape < best['wmape']:
                    best.update({'wmape': wmape, 'forecast': pred, 'params': {**valid_p, 'exog_cols': exog_cols}, 'error': None})
            except Exception as e:
                if best['error'] is None:
                    best['error'] = f"Prophet: {str(e)[:50]}"
                continue
    except Exception as e: 
        best['error'] = str(e)
    return best

@lru_cache(maxsize=1)
def prophet_backend_available():
    try:
        _ = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=False,
            daily_seasonality=False,
            uncertainty_samples=0,
        )
        return True, ""
    except Exception as e:
        return False, str(e)

def fit_shared_arima(train_data, mode='smart'):
    train_values = np.maximum(train_data.values.flatten(), 0)
    train_log, n = np.log1p(train_values), len(train_values)

    # fast 模式快速路径：优先使用轻量 ARIMA，避免长时间超时
    if mode == 'fast':
        try:
            sm_model = SMARIMA(train_log, order=(1, 1, 0))
            sm_fit = sm_model.fit(method_kwargs={"maxiter": 50})
            pred = np.expm1(sm_fit.predict(start=0, end=len(train_log) - 1))
            if not np.any(np.isnan(pred)) and not np.any(np.isinf(pred)):
                return sm_fit, pred, True, None
        except Exception as e:
            return None, None, False, f"fast_smarima: {str(e)[:120]}"

    m, use_seasonal = (4, False) if n < 52 else ((13, n>=26) if n < 104 else ((26, True) if n < 156 else (52, True)))
    
    strategies = [('fixed_minimal', (1,1,0), (0,0,0,0)), ('fixed_ar1', (1,0,0), (0,0,0,0)), ('fixed_simple', (1,1,1), (0,0,0,0))] if mode == 'fast' else [
        ('seasonal_simple', (1,1,1), (0,1,1,m) if use_seasonal else (0,0,0,0)), ('auto_limited', None, None),
        ('seasonal_minimal', (1,1,0), (0,1,0,m) if use_seasonal else (0,0,0,0)), ('nonseasonal', (1,1,1), (0,0,0,0)), ('minimal', (0,1,1), (0,0,0,0))]
    
    last_error = None
    for name, order, s_order in strategies:
        try:
            if name == 'auto_limited':
                am = pm.auto_arima(train_log, seasonal=use_seasonal, m=m if use_seasonal else 1, d=1, D=1 if use_seasonal else 0, max_p=2, max_q=2, max_P=1, max_Q=1, max_order=4, stepwise=True, n_fits=15, suppress_warnings=True, n_jobs=1)
            else:
                am = pm.ARIMA(order=order, seasonal_order=s_order)
                with suppress_stdout_stderr(): am.fit(train_log)
            pred = np.expm1(am.predict_in_sample())
            if np.any(np.isnan(pred)) or np.any(np.isinf(pred)) or np.mean(pred) < 0 or (np.mean(train_values) > 0 and np.mean(pred) > np.mean(train_values)*10): continue
            return am, pred, True
        except Exception as e:
            last_error = f"{name}: {str(e)[:120]}"
            continue
    return None, None, False, last_error

def build_tcn_model(input_shape, neurons):
    try:
        inputs = Input(shape=input_shape)
        x = Conv1D(filters=neurons, kernel_size=2, padding='causal', dilation_rate=1, activation='relu')(inputs)
        x = Dropout(0.1)(x)
        if input_shape[0] >= 4: x = Conv1D(filters=neurons, kernel_size=2, padding='causal', dilation_rate=2, activation='relu')(x)
        x = Lambda(lambda t: t[:, -1, :])(x)
        x = Dense(neurons // 2, activation='relu')(x)
        return Model(inputs, Dense(1)(x))
    except: return Sequential([LSTM(neurons, input_shape=input_shape, activation='tanh'), Dense(1)])

def build_nbeats_model(input_shape, neurons):
    inputs = Input(shape=input_shape); flat = Flatten()(inputs); flat_dim = input_shape[0]*input_shape[1]
    h1 = Dropout(0.1)(Dense(neurons, activation='relu')(flat))
    backcast1 = Dense(flat_dim, activation='linear')(h1); forecast1 = Dense(1, activation='linear')(h1)
    resid = Lambda(lambda x: x[0] - x[1])([flat, backcast1])
    forecast2 = Dense(1, activation='linear')(Dense(neurons, activation='relu')(resid))
    return Model(inputs, Add()([forecast1, forecast2]))

def optimize_dl_with_arima(train_data, test_data, dl_type, arima_model, train_arima, mode='full'):
    best = {'name': {'lstm':'SARIMA+LSTM', 'tcn':'SARIMA+TCN', 'nbeats':'SARIMA+N-BEATS'}[dl_type], 'wmape': float('inf'), 'forecast': None, 'params': None, 'error': None}
    if not arima_model: return best
    try:
        test_values = test_data.values.flatten()
        try:
            arima_raw = arima_model.predict(n_periods=len(test_values))
        except TypeError:
            arima_raw = arima_model.forecast(steps=len(test_values))
        test_arima = np.expm1(np.asarray(arima_raw).flatten())
        if len(test_arima) != len(test_values):
            if len(test_arima) > len(test_values):
                test_arima = test_arima[: len(test_values)]
            else:
                pad_val = float(test_arima[-1]) if len(test_arima) > 0 else float(np.mean(train_data.values.flatten()))
                test_arima = np.pad(test_arima, (0, len(test_values) - len(test_arima)), constant_values=pad_val)

        train_values = train_data.values.flatten()
        train_arima_arr = np.asarray(train_arima).flatten()
        if len(train_arima_arr) != len(train_values):
            if len(train_arima_arr) > len(train_values):
                train_arima_arr = train_arima_arr[-len(train_values):]
            else:
                pad_val = float(train_arima_arr[0]) if len(train_arima_arr) > 0 else 0.0
                train_arima_arr = np.pad(train_arima_arr, (len(train_values) - len(train_arima_arr), 0), constant_values=pad_val)

        resids = np.nan_to_num((train_values - train_arima_arr).reshape(-1, 1), nan=0.0)
        scaler = MinMaxScaler((-1, 1)); res_scaled = scaler.fit_transform(resids)
        
        cfg = SearchConfig.get(mode)
        dl_cfg = cfg.get('dl_residual', {})
        combs = list(itertools.product(
            dl_cfg.get('look_back', [4]) if isinstance(dl_cfg.get('look_back', [4]), list) else [dl_cfg.get('look_back', 4)],
            dl_cfg.get('neurons', [32]) if isinstance(dl_cfg.get('neurons', [32]), list) else [dl_cfg.get('neurons', 32)],
            dl_cfg.get('learning_rate', [0.01]) if isinstance(dl_cfg.get('learning_rate', [0.01]), list) else [dl_cfg.get('learning_rate', 0.01)],
            dl_cfg.get('dropout', [0.1]) if isinstance(dl_cfg.get('dropout', [0.1]), list) else [dl_cfg.get('dropout', 0.1)]
        ))
        if len(combs) > cfg.get('max_combinations', 20): combs = random.sample(combs, cfg.get('max_combinations', 20))
        if mode == 'fast': combs = combs[:3]
        
        for lb, neu, lr, drop in combs:
            try:
                X, Y = np.array([res_scaled[i:i+lb, 0] for i in range(len(res_scaled)-lb)]), np.array([res_scaled[i+lb, 0] for i in range(len(res_scaled)-lb)])
                if len(X) < 10: continue
                X = X.reshape(X.shape[0], X.shape[1], 1)
                tf.keras.backend.clear_session()
                
                if dl_type == 'lstm': m = Sequential([LSTM(neu, input_shape=(lb, 1), activation='tanh'), Dropout(drop), Dense(1)])
                elif dl_type == 'tcn': m = build_tcn_model((lb, 1), neu)
                else: m = build_nbeats_model((lb, 1), neu)
                
                m.compile(loss='mse', optimizer=Adam(lr))
                m.fit(X, Y, epochs=dl_cfg.get('epochs', 20), batch_size=min(16, max(4, len(X)//4)), verbose=0, callbacks=[EarlyStopping(monitor='loss', patience=5, restore_best_weights=True)])
                
                curr = res_scaled[-lb:].flatten()
                pred_resids = []
                for _ in range(len(test_values)):
                    p = m.predict(curr.reshape(1, lb, 1), verbose=0)[0, 0]
                    pred_resids.append(p); curr = np.append(curr[1:], p)

                resid_pred = scaler.inverse_transform(np.array(pred_resids).reshape(-1, 1)).flatten()
                if len(resid_pred) != len(test_arima):
                    min_len = min(len(resid_pred), len(test_arima))
                    resid_pred = resid_pred[:min_len]
                    test_arima_local = test_arima[:min_len]
                    test_values_local = test_values[:min_len]
                else:
                    test_arima_local = test_arima
                    test_values_local = test_values

                final_pred = np.maximum(test_arima_local + resid_pred, 0)
                wmape = calculate_wmape(test_values_local, final_pred)
                if wmape < best['wmape']:
                    arima_order = getattr(arima_model, 'order', None)
                    arima_seasonal_order = getattr(arima_model, 'seasonal_order', None)
                    if arima_order is None and hasattr(arima_model, 'model') and hasattr(arima_model.model, 'order'):
                        arima_order = arima_model.model.order
                    if arima_seasonal_order is None and hasattr(arima_model, 'model') and hasattr(arima_model.model, 'seasonal_order'):
                        arima_seasonal_order = arima_model.model.seasonal_order
                    best.update({'wmape': wmape, 'forecast': final_pred, 'params': {'look_back': lb, 'neurons': neu, 'epochs': dl_cfg.get('epochs', 20), 'learning_rate': lr, 'dropout': drop, 'arima_order': arima_order, 'arima_seasonal_order': arima_seasonal_order, 'dl_type': dl_type}, 'error': None})
            except Exception as e:
                if best['error'] is None:
                    best['error'] = f"{dl_type}: {str(e)[:50]}"
                continue
    except Exception as e: 
        best['error'] = str(e)
    return best

def _identify_fusion_regime(full_series):
    values = np.asarray(full_series.values if hasattr(full_series, "values") else full_series, dtype=float).flatten()
    if len(values) == 0:
        return {
            'regime': 'normal', 'is_low_signal': False, 'is_high_volatility': False,
            'zero_ratio': 0.0, 'demand_density': 1.0, 'hist_cv': 0.0,
            'recent_mean': 0.0, 'recent_median': 0.0, 'recent_p90': 0.0
        }

    recent = np.maximum(values[-min(26, len(values)):], 0)
    recent_mean = float(np.mean(recent))
    recent_median = float(np.median(recent))
    recent_p90 = float(np.percentile(recent, 90))
    zero_ratio = float(np.mean(recent <= 0))
    demand_density = float(np.mean(recent > 0))
    hist_cv = float(np.std(recent) / (recent_mean + 1e-6)) if recent_mean > 0 else 0.0
    p95 = float(np.percentile(recent, 95))
    p50 = max(float(np.percentile(recent, 50)), 1e-6)
    spike_ratio = p95 / p50

    is_low_signal = (zero_ratio >= 0.55) or (demand_density <= 0.45) or (recent_mean <= 1.0 and recent_median <= 1.0)
    is_high_volatility = (hist_cv >= 1.25) or (spike_ratio >= 4.0)
    if is_low_signal and is_high_volatility:
        regime = 'mixed'
    elif is_low_signal:
        regime = 'low_signal'
    elif is_high_volatility:
        regime = 'high_volatility'
    else:
        regime = 'normal'

    return {
        'regime': regime,
        'is_low_signal': is_low_signal,
        'is_high_volatility': is_high_volatility,
        'zero_ratio': zero_ratio,
        'demand_density': demand_density,
        'hist_cv': hist_cv,
        'recent_mean': recent_mean,
        'recent_median': recent_median,
        'recent_p90': recent_p90
    }


def _compute_fusion_confidence(pred_matrix, wmapes, regime_info):
    center = np.mean(pred_matrix, axis=1)
    disagreement = np.mean(np.std(pred_matrix, axis=1) / (np.abs(center) + 1e-6))
    consensus = float(np.clip(1.0 - disagreement, 0.0, 1.0))

    wmape_best = float(np.min(wmapes))
    wmape_span = float(np.max(wmapes) - np.min(wmapes)) if len(wmapes) > 1 else 0.0
    quality = float(np.clip(1.0 - wmape_best, 0.0, 1.0))
    stability = float(np.clip(1.0 - wmape_span, 0.0, 1.0))

    confidence = 0.45 * consensus + 0.35 * quality + 0.20 * stability
    if regime_info['is_low_signal']:
        confidence -= 0.08
    if regime_info['is_high_volatility']:
        confidence -= 0.05
    return float(np.clip(confidence, 0.12, 0.95))


def _tail_penalized_wmape(y_true, y_pred, regime_info, fusion_confidence):
    raw_wmape = calculate_wmape(y_true, y_pred)
    y_true = np.asarray(y_true, dtype=float).flatten()
    y_pred = np.asarray(y_pred, dtype=float).flatten()

    denom = np.maximum(np.abs(y_true), 1.0)
    ape = np.abs(y_true - y_pred) / denom
    tail_85 = float(np.percentile(ape, 85))
    tail_95 = float(np.percentile(ape, 95))

    overshoot_ratio = float(np.sum(np.maximum(y_pred - y_true, 0)) / (np.sum(np.abs(y_true)) + 1e-6))
    tail_penalty = max(0.0, tail_85 - 0.45) * 0.22 + max(0.0, tail_95 - 0.75) * 0.12
    if regime_info['is_low_signal']:
        tail_penalty += max(0.0, overshoot_ratio - 0.25) * 0.18
    if regime_info['is_high_volatility']:
        pred_mean = float(np.mean(y_pred))
        pred_cv = float(np.std(y_pred) / (pred_mean + 1e-6)) if pred_mean > 0 else 0.0
        hist_cv = max(float(regime_info.get('hist_cv', 0.0)), 0.01)
        if pred_cv > hist_cv * 1.8:
            tail_penalty += min(0.22, (pred_cv / hist_cv - 1.8) * 0.06)

    confidence_penalty = (1.0 - fusion_confidence) * 0.08
    effective_wmape = raw_wmape * (1.0 + tail_penalty + confidence_penalty)
    meta = {
        'tail_ape_p85': tail_85,
        'tail_ape_p95': tail_95,
        'overshoot_ratio': overshoot_ratio,
        'tail_penalty': tail_penalty,
        'confidence_penalty': confidence_penalty
    }
    return float(raw_wmape), float(effective_wmape), meta


def _weighted_median_forecast(pred_matrix, weights):
    matrix = np.asarray(pred_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        return np.array([])
    weights = np.asarray(weights, dtype=float).flatten()
    if len(weights) != matrix.shape[1]:
        weights = np.ones(matrix.shape[1], dtype=float)
    weights = np.maximum(weights, 0.0)
    if np.sum(weights) < 1e-6:
        weights = np.ones(matrix.shape[1], dtype=float) / matrix.shape[1]
    else:
        weights = weights / np.sum(weights)

    out = np.zeros(matrix.shape[0], dtype=float)
    for i in range(matrix.shape[0]):
        order = np.argsort(matrix[i])
        values_sorted = matrix[i, order]
        w_sorted = weights[order]
        cdf = np.cumsum(w_sorted)
        idx = min(np.searchsorted(cdf, 0.5, side='left'), len(values_sorted) - 1)
        out[i] = values_sorted[idx]
    return out


def _apply_fusion_guardrail(forecast, full_data, regime, confidence, fallback_value):
    res = np.asarray(forecast, dtype=float).flatten().copy()
    hist = np.asarray(full_data.values if hasattr(full_data, "values") else full_data, dtype=float).flatten()
    if len(res) == 0 or len(hist) == 0:
        return np.maximum(res, 0)

    recent = np.maximum(hist[-min(26, len(hist)):], 0)
    recent_mean = float(np.mean(recent))
    recent_median = float(np.median(recent))
    recent_p90 = float(np.percentile(recent, 90))
    hist_cv = float(np.std(recent) / (recent_mean + 1e-6)) if recent_mean > 0 else 0.0
    base_anchor = max(recent_median, recent_mean, float(fallback_value), 0.0)

    if regime in ('low_signal', 'mixed'):
        cap = max(recent_p90 * 1.8, base_anchor * 1.6 + 1.0)
        res = np.minimum(res, cap)
        shrink = min(0.55, 0.25 + (1.0 - confidence) * 0.45)
        anchor = np.full_like(res, max(recent_median, base_anchor * 0.8))
        res = (1.0 - shrink) * res + shrink * anchor

    if regime in ('high_volatility', 'mixed'):
        target_cv = max(hist_cv * 0.9, 0.10)
        pred_mean = float(np.mean(res))
        pred_cv = float(np.std(res) / (pred_mean + 1e-6)) if pred_mean > 0 else 0.0
        if pred_cv > target_cv * 1.7 and pred_cv > 0:
            scale = (target_cv * 1.7) / pred_cv
            center = pred_mean
            res = center + (res - center) * scale

    if confidence < 0.25:
        conservative = np.full_like(res, base_anchor)
        res = 0.6 * res + 0.4 * conservative

    return np.maximum(res, 0)


def optimize_ensemble(base_results, test_data, mode='full', train_data=None):
    valid = [r for r in base_results if r['forecast'] is not None and r['wmape'] < float('inf')]
    if len(valid) < 2:
        return []

    test_values = test_data.values.flatten()
    preds = np.column_stack([r['forecast'] for r in valid])
    names, wmapes = [r['name'] for r in valid], np.array([r['wmape'] for r in valid], dtype=float)

    full_series = pd.concat([train_data, test_data]) if train_data is not None else test_data
    s_str, _, d_per = detect_seasonality_strength(full_series)
    s_pat = extract_seasonal_pattern(full_series, d_per)
    t_dir, t_str, t_slope = detect_trend_strength(full_series)
    t_scores = np.array([calculate_trend_consistency(preds[:, i], t_dir, t_slope) for i in range(len(valid))], dtype=float)

    seas_mask = np.array([any(x in n for x in ['Prophet', 'SARIMA']) for n in names])
    regime_info = _identify_fusion_regime(full_series)
    base_confidence = _compute_fusion_confidence(preds, wmapes, regime_info)

    methods = SearchConfig.get(mode).get('ensemble', {}).get('methods', ['weighted'])
    results = []

    def append_candidate(name, forecast, params, confidence_boost=0.0):
        forecast = np.maximum(np.asarray(forecast, dtype=float).flatten(), 0)
        if len(forecast) != len(test_values):
            return
        median_line = np.median(preds, axis=1)
        deviation = np.mean(np.abs(forecast - median_line) / (np.abs(median_line) + 1e-6))
        candidate_consensus = float(np.clip(1.0 - deviation, 0.0, 1.0))
        confidence = float(np.clip(0.65 * base_confidence + 0.35 * candidate_consensus + confidence_boost, 0.08, 0.97))
        raw_wmape, effective_wmape, tail_meta = _tail_penalized_wmape(test_values, forecast, regime_info, confidence)

        candidate_params = {
            **params,
            'fusion_regime': regime_info['regime'],
            'fusion_confidence': round(confidence, 4),
            'raw_wmape': round(raw_wmape, 6),
            'effective_wmape': round(effective_wmape, 6),
            'tail_penalty': round(tail_meta['tail_penalty'], 6),
            'confidence_penalty': round(tail_meta['confidence_penalty'], 6),
            'tail_ape_p85': round(tail_meta['tail_ape_p85'], 6),
            'tail_ape_p95': round(tail_meta['tail_ape_p95'], 6),
            'overshoot_ratio': round(tail_meta['overshoot_ratio'], 6),
            'regime_zero_ratio': round(regime_info['zero_ratio'], 6),
            'regime_demand_density': round(regime_info['demand_density'], 6),
            'regime_hist_cv': round(regime_info['hist_cv'], 6),
            'regime_recent_mean': round(regime_info['recent_mean'], 6),
            'regime_recent_p90': round(regime_info['recent_p90'], 6)
        }
        results.append({'name': name, 'wmape': effective_wmape, 'forecast': forecast, 'params': candidate_params})

    if 'simple' in methods:
        p = np.mean(preds, axis=1)
        append_candidate('Ensemble_Avg', p, {'method': 'simple', 'base_models': names}, confidence_boost=-0.02)

    if 'weighted' in methods:
        w_wmape = 1 / (wmapes + 1e-6)
        w_wmape /= w_wmape.sum()
        p = np.average(preds, axis=1, weights=w_wmape)
        append_candidate(
            'Ensemble_Wgt', p,
            {'method': 'wmape_weighted', 'base_models': names, 'weights': list(w_wmape), 'wmape_weights': list(w_wmape)},
            confidence_boost=0.02
        )

        if s_str > 0.2 and seas_mask.any():
            w_seas = w_wmape.copy()
            w_seas[seas_mask] *= (1 + s_str * 1.5)
            w_seas /= w_seas.sum()
            p_seas = np.average(preds, axis=1, weights=w_seas)
            append_candidate(
                'Ensemble_Seas', p_seas,
                {'method': 'seasonal_weighted', 'base_models': names, 'weights': list(w_seas), 'wmape_weights': list(w_wmape), 'seasonal_strength': s_str}
            )

        if t_str > 0.2 and t_dir != 'flat':
            w_trend = w_wmape * (1 + t_str * 2 * t_scores)
            w_trend /= w_trend.sum()
            p_trend = np.average(preds, axis=1, weights=w_trend)
            append_candidate(
                'Ensemble_Trend', p_trend,
                {'method': 'trend_weighted', 'base_models': names, 'weights': list(w_trend), 'trend_direction': t_dir, 'trend_strength': t_str}
            )

        if t_str > 0.15 or s_str > 0.15:
            s_scores = np.ones(len(names)) * 0.5
            s_scores[seas_mask] = 1.0 + s_str
            s_scores /= s_scores.sum()
            t_scores_norm = np.maximum(t_scores, 0.2)
            t_scores_norm /= t_scores_norm.sum()
            a, b, g = 0.5, min(s_str * 0.4, 0.25), min(t_str * 0.4, 0.25)
            total = a + b + g
            a, b, g = a / total, b / total, g / total
            w_comb = a * w_wmape + b * s_scores + g * t_scores_norm
            w_comb = np.maximum(w_comb, 0)
            w_comb /= w_comb.sum()
            p_comb = np.average(preds, axis=1, weights=w_comb)
            append_candidate(
                'Ensemble_TS', p_comb,
                {'method': 'trend_seasonal_combined', 'base_models': names, 'weights': list(w_comb), 'wmape_weights': list(w_wmape), 'trend_direction': t_dir, 'trend_strength': t_str, 'seasonal_strength': s_str, 'trend_consistency_scores': list(t_scores)}
            )

        if regime_info['regime'] != 'normal':
            p_robust = _weighted_median_forecast(preds, w_wmape)
            if regime_info['is_low_signal']:
                robust_cap = max(regime_info['recent_p90'] * 1.6, regime_info['recent_mean'] * 1.5 + 1.0)
                p_robust = np.minimum(p_robust, robust_cap)
            append_candidate(
                'Ensemble_Robust', p_robust,
                {'method': 'weighted_median_robust', 'base_models': names, 'weights': list(w_wmape), 'wmape_weights': list(w_wmape)},
                confidence_boost=0.05
            )

    if 'stacking' in methods:
        try:
            meta = Ridge(alpha=1.0, fit_intercept=True)
            meta.fit(preds, test_values)
            p_stack = meta.predict(preds)
            w_wmape = 1 / (wmapes + 1e-6)
            w_wmape /= w_wmape.sum()

            if (t_str > 0.25 and t_dir != 'flat') and (detect_trend_strength(pd.Series(p_stack))[0] != t_dir or np.any(meta.coef_ < -0.1)):
                best_t_idx = np.argmax(t_scores)
                if detect_trend_strength(pd.Series(preds[:, best_t_idx]))[0] == t_dir:
                    corr_weight = min(t_str * 0.5, 0.35)
                    p_stack = (1 - corr_weight) * p_stack + corr_weight * preds[:, best_t_idx]
                else:
                    w_t = w_wmape * (1 + t_scores)
                    p_stack = np.average(preds, axis=1, weights=w_t / w_t.sum())

            if s_str > 0.25 and len(test_values) >= 4 and train_data is not None:
                t_idx = get_seasonal_indices(test_data.index, train_data.index[-1], d_per)
                s_corr = np.array([(s_pat[idx % len(s_pat)] - 1.0) * np.mean(test_values) * s_str * 0.1 if idx < len(s_pat) else 0 for idx in t_idx])
                p_corr = p_stack + s_corr
                if calculate_wmape(test_values, p_corr) < calculate_wmape(test_values, p_stack):
                    p_stack = p_corr

            p_stack = np.maximum(p_stack, 0)
            append_candidate(
                'Ensemble_Stack', p_stack,
                {'method': 'stacking_enhanced', 'base_models': names, 'weights': list(meta.coef_), 'wmape_weights': list(w_wmape), 'trend_direction': t_dir, 'trend_strength': t_str, 'seasonal_strength': s_str, 'detected_period': d_per, 'trend_consistency_scores': list(t_scores), 'seasonal_pattern': list(s_pat[:min(12, len(s_pat))])}
            )
        except:
            pass

    return results

def predict_future(full_data, winner_info, n_future=16, full_exog=None, future_exog=None, base_results=None):
    name, params = winner_info['name'], winner_info.get('params', {})
    fb = float(full_data.iloc[-8:].mean())
    
    if 'Ensemble' in name:
        bns, weights = params.get('base_models', []), params.get('weights', [])
        w_wmape = params.get('wmape_weights', weights)
        t_dir, t_str = params.get('trend_direction', 'flat'), params.get('trend_strength', 0)
        s_str, d_per = params.get('seasonal_strength', 0), params.get('detected_period', 52)
        fusion_regime = params.get('fusion_regime', 'normal')
        fusion_confidence = float(params.get('fusion_confidence', 0.5))
        
        preds, valid_w = [], []
        for i, bn in enumerate(bns):
            br = next((r for r in (base_results or []) if r['name'] == bn), None)
            if br:
                try:
                    p = safe_predictions(predict_future(full_data, br, n_future, full_exog, future_exog, base_results), fb, bn)
                    if not np.all(p == 0):
                        preds.append(p)
                        valid_w.append(weights[i] if i<len(weights) else 1.0/len(bns))
                except: pass
        
        if not preds: return np.full(n_future, fb)
        valid_w = np.array(valid_w)
        if np.any(valid_w < -0.1): valid_w = np.array(w_wmape[:len(preds)])
        if np.sum(np.abs(valid_w)) < 1e-6: valid_w = np.ones(len(preds))/len(preds)
        valid_w = np.abs(valid_w) / np.abs(valid_w).sum()
        
        # 获取初步融合结果
        res = np.average(np.array(preds).T, axis=1, weights=valid_w)
        
        # =========================================================================
        # 👑【核心升级：Ensemble 趋势与季节的暴力矫正引擎】👑
        # =========================================================================
        res_mean = np.mean(res)
        
        # 1. 强制季节对齐 (Seasonality Hard Injection)
        if s_str > 0.15: # 只要有一定季节性就不允许被抹平
            try:
                s_pat = extract_seasonal_pattern(full_data, d_per)
                f_idx = get_seasonal_indices(pd.date_range(full_data.index[-1], periods=n_future+1, freq='W')[1:], full_data.index[-1], d_per)
                s_fac = np.array([s_pat[idx%len(s_pat)] for idx in f_idx])
                
                # 融合线与强季节线进行权重混合
                seasonal_line = res_mean * s_fac
                res = res * (1 - s_str * 0.8) + seasonal_line * (s_str * 0.8)
            except: pass

        # 2. 强制趋势跟随 (Trend Hard Alignment)
        if t_str > 0.15 and t_dir != 'flat':
            try:
                recent_hist = full_data.values[-min(26, len(full_data)):]
                hist_slope, _, _, _, _ = stats.linregress(np.arange(len(recent_hist)), recent_hist)
                pred_slope, _, _, _, _ = stats.linregress(np.arange(n_future), res)
                
                # 如果预测趋势方向相反，或者斜率连历史的一半都不到
                if (t_dir == 'up' and pred_slope < hist_slope * 0.5) or (t_dir == 'down' and pred_slope > hist_slope * 0.5):
                    # 补足到历史斜率的 60%
                    target_slope = hist_slope * 0.6
                    slope_diff = target_slope - pred_slope
                    trend_correction = slope_diff * np.arange(n_future)
                    # 以中心点为轴施加倾斜，保证均值不变
                    res += trend_correction - np.mean(trend_correction) 
            except: pass

        # 3. 强制波动率/振幅复原 (Variance Restitution)
        recent_hist_year = full_data.values[-min(52, len(full_data)):]
        hist_cv = np.std(recent_hist_year) / (np.mean(recent_hist_year) + 1e-5)
        pred_cv = np.std(res) / (np.mean(res) + 1e-5)
        
        # 如果预测线的波动不到历史波动的 60%
        if pred_cv < hist_cv * 0.6 and pred_cv > 0:
            # 计算拉伸系数 (强行把振幅放大)
            stretch_ratio = min((hist_cv * 0.6) / pred_cv, 3.0) 
            res_center = np.mean(res)
            res = res_center + (res - res_center) * stretch_ratio

        if fusion_confidence < 0.28 and len(preds) >= 2:
            robust_future = _weighted_median_forecast(np.array(preds).T, valid_w)
            if len(robust_future) == len(res):
                blend = min(0.5, 0.3 + (0.28 - fusion_confidence) * 0.8)
                res = (1 - blend) * res + blend * robust_future

        res = _apply_fusion_guardrail(res, full_data, fusion_regime, fusion_confidence, fb)
            
        # =========================================================================
            
        return safe_predictions(np.maximum(res, 0), fb, name)

    elif name in ['XGBoost', 'LightGBM', 'CatBoost']:
        fe = params.get('feat_eng')
        if not fe: return np.full(n_future, fb)
        fd_diff, fd_log = make_log_diff(full_data)
        fe_exog = full_exog.iloc[1:].copy().set_index(fd_diff.index) if full_exog is not None and len(full_exog)>0 else None
        X_f, y_f = fe.make_features_for_prediction(fd_diff, fe_exog)
        if len(X_f) < 5: return np.full(n_future, fb)
        mp = {k: v for k, v in params.items() if k not in ['feat_eng', 'train_last_log', 'model_type', 'exog_cols']}
        m_type = params.get('model_type', 'xgboost')
        
        if m_type == 'xgboost': m = XGBRegressor(**mp, objective='reg:squarederror', n_jobs=-1, random_state=42)
        elif m_type == 'lgbm': m = LGBMRegressor(**mp, n_jobs=-1, random_state=42, verbose=-1)
        else: m = get_catboost_regressor()(**mp, loss_function='MAE', verbose=0, random_state=42)
        m.fit(X_f, y_f)
        return safe_predictions(tree_recursive_predict(m, fd_diff, fd_log, n_future, fe, X_f['time_idx'].iloc[-1]+1, future_exog, fe_exog), fb, name)
        
    elif 'SARIMA' in name:
        try:
            fv, f_log = full_data.values.flatten(), np.log1p(np.maximum(full_data.values.flatten(), 0))
            am = pm.ARIMA(order=params.get('arima_order', (1,1,1)), seasonal_order=params.get('arima_seasonal_order', (0,1,1,52)))
            try: 
                with suppress_stdout_stderr(): am.fit(f_log)
            except:
                am = pm.ARIMA(order=(1,1,1), seasonal_order=(0,1,1,52))
                with suppress_stdout_stderr(): am.fit(f_log)
                
            f_arima = np.expm1(am.predict_in_sample())
            fut_arima = np.maximum(np.expm1(am.predict(n_periods=n_future)), 0)
            
            resids = np.nan_to_num((fv - f_arima).reshape(-1,1), nan=0.0)
            scaler = MinMaxScaler((-1,1)); r_s = scaler.fit_transform(resids)
            lb, neu, dt = params.get('look_back', 4), params.get('neurons', 32), params.get('dl_type', 'lstm')
            
            X, Y = np.array([r_s[i:i+lb,0] for i in range(len(r_s)-lb)]), np.array([r_s[i+lb,0] for i in range(len(r_s)-lb)])
            if len(X) < 5: return safe_predictions(fut_arima, fb, name)
            X = X.reshape(X.shape[0], X.shape[1], 1)
            tf.keras.backend.clear_session()
            if dt == 'lstm': m = Sequential([LSTM(neu, input_shape=(lb,1), activation='tanh'), Dropout(0.1), Dense(1)])
            elif dt == 'tcn': m = build_tcn_model((lb,1), neu)
            else: m = build_nbeats_model((lb,1), neu)
            
            m.compile(loss='mse', optimizer=Adam(0.01))
            m.fit(X, Y, epochs=params.get('epochs', 20), batch_size=min(16, max(4, len(X)//4)), verbose=0, callbacks=[EarlyStopping(monitor='loss', patience=3)])
            
            curr, p_r = r_s[-lb:].flatten(), []
            for _ in range(n_future):
                p = m.predict(curr.reshape(1,lb,1), verbose=0)[0,0]; p_r.append(p); curr = np.append(curr[1:], p)
                
            p_r = scaler.inverse_transform(np.array(p_r).reshape(-1,1)).flatten()
            p_r = np.clip(p_r, -3*np.std(fv-f_arima), 3*np.std(fv-f_arima))
            res = fut_arima + p_r
            if np.any(res < 0) or np.mean(res) < np.mean(fv)*0.1: res = fut_arima
            return safe_predictions(res, fb, name)
        except: return np.full(n_future, fb)

    elif name == 'Prophet':
        try:
            exog_cols = params.get('exog_cols', [])
            m = Prophet(**{k: v for k, v in params.items() if k in PROPHET_VALID_PARAMS}, yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
            df_full = full_data.reset_index(); df_full.columns = ['ds', 'y']; df_full['ds'] = pd.to_datetime(df_full['ds'])
            if exog_cols and full_exog is not None:
                er = full_exog.reset_index(); er.columns = ['ds'] + list(full_exog.columns); er['ds'] = pd.to_datetime(er['ds'])
                df_full = df_full.merge(er, on='ds', how='left')
                for c in exog_cols:
                    if c in df_full.columns: m.add_regressor(c); df_full[c] = df_full[c].fillna(df_full[c].mean())
            with suppress_stdout_stderr(): m.fit(df_full)
            future = m.make_future_dataframe(periods=n_future, freq='W')
            if exog_cols and future_exog is not None:
                ce = pd.concat([full_exog, future_exog]).reset_index(); ce.columns = ['ds'] + list(full_exog.columns); ce['ds'] = pd.to_datetime(ce['ds'])
                future = future.merge(ce, on='ds', how='left')
                for c in exog_cols:
                    if c in future.columns: future[c] = future[c].fillna(future[c].mean())
            return safe_predictions(m.predict(future)['yhat'].iloc[-n_future:].values, fb, name)
        except: return np.full(n_future, fb)

    return np.full(n_future, fb)

def run_all_models(train_data, test_data, mode='full', train_exog=None, test_exog=None, verbose=True):
    base_results = []
    cfg = SearchConfig.get(mode)
    
    def create_feat_eng(): return FeatureEngineer(lags=[1, 2, 4], rolling_windows=[4, 8])
    
    print(f"\n   [RUN] Running models (mode={mode})...")
    
    # Prophet: 单进程运行（Windows多进程兼容性问题）
    print(f"      [MODEL] Prophet...", end=" ", flush=True)
    t0 = time.time()
    try:
        import os
        # 设置Prophet环境变量
        os.environ['STAN_BACKEND'] = 'CMDSTANPY'
        os.environ['CMDSTANPY_COMPILE'] = 'false'
        prophet_res = optimize_prophet(train_data, test_data, mode, train_exog, test_exog)
        el = time.time() - t0
        if prophet_res and prophet_res['forecast'] is not None and prophet_res['wmape'] < float('inf'):
            prophet_res['training_time'] = el
            base_results.append(prophet_res)
            print(f"WMAPE={prophet_res['wmape']:.2%} ({el:.1f}s)")
        else:
            error_msg = str(prophet_res.get('error', 'Unknown')) if prophet_res else 'Unknown'
            print(f"Failed: {error_msg[:100]}")
    except Exception as e:
        print(f"Failed: {str(e)[:100]}")
    
    non_arima = [
        ('XGBoost', partial(optimize_tree_model, 'xgboost', train_data, test_data, create_feat_eng(), mode, train_exog, test_exog)),
        ('LightGBM', partial(optimize_tree_model, 'lgbm', train_data, test_data, create_feat_eng(), mode, train_exog, test_exog))
    ]
    # 【修复处】
    if get_catboost_regressor(): 
        non_arima.append(('CatBoost', partial(optimize_tree_model, 'catboost', train_data, test_data, create_feat_eng(), mode, train_exog, test_exog)))
    
    for name, func in non_arima:
        print(f"      [MODEL] {name}...", end=" ", flush=True)
        t0 = time.time()
        res = run_with_timeout(func, cfg.get('model_timeout', 90))
        el = time.time() - t0
        if res and res['forecast'] is not None and res['wmape'] < float('inf'):
            res['training_time'] = el; base_results.append(res); print(f"WMAPE={res['wmape']:.2%} ({el:.1f}s)")
        else: 
            error_msg = str(res.get('error', 'Unknown')) if res else 'Unknown'
            print(f"Failed: {error_msg[:100]}")  # 显示更多错误信息

    dl_models = ['lstm']
    if cfg.get('enable_tcn', False): dl_models.append('tcn')
    if cfg.get('enable_nbeats', False): dl_models.append('nbeats')
    
    am, t_arima = None, None
    if dl_models:
        print(f"      [MODEL] Fitting ARIMA...", end=" ", flush=True)
        t0 = time.time()
        if mode == 'fast':
            # fast 模式避免多进程启动开销，优先同步执行
            res = fit_shared_arima(train_data, mode)
        else:
            res = run_with_timeout(partial(fit_shared_arima, train_data, mode), cfg.get('arima_timeout', 40))
        el = time.time() - t0
        if isinstance(res, (tuple, list)) and len(res) >= 3 and res[2]:
            am, t_arima = res[0], res[1]
            arima_order = getattr(am, "order", None)
            if arima_order is None and hasattr(am, "model") and hasattr(am.model, "order"):
                arima_order = am.model.order
            print(f"Done ({el:.1f}s, order={arima_order})")
        else:
            arima_err = None
            if isinstance(res, (tuple, list)) and len(res) >= 4:
                arima_err = res[3]
            elif isinstance(res, dict):
                arima_err = res.get('error')
            if arima_err:
                print(f"Failed ({el:.1f}s): {str(arima_err)[:120]}")
            else:
                print(f"Failed ({el:.1f}s)")
        
    if am:
        for dt in dl_models:
            name = f"SARIMA+{dt.upper()}"
            print(f"      [MODEL] {name}...", end=" ", flush=True)
            t0 = time.time()
            res = run_with_timeout(partial(optimize_dl_with_arima, train_data, test_data, dt, am, t_arima, mode), cfg.get('dl_timeout', 50))
            el = time.time() - t0
            if res and res['forecast'] is not None and res['wmape'] < float('inf'):
                res['training_time'] = el; base_results.append(res); print(f"WMAPE={res['wmape']:.2%} ({el:.1f}s)")
            else: 
                error_msg = str(res.get('error', 'Unknown')) if res else 'Unknown'
                print(f"Failed: {error_msg[:100]}")  # 显示更多错误信息
            
    if len(base_results) >= 2:
        print(f"      [MODEL] Ensemble...", end=" ", flush=True)
        try:
            ens_res = optimize_ensemble(base_results, test_data, mode, train_data)
            for e in ens_res: e['training_time'] = 0.1
            base_results.extend(ens_res)
            print(f"Done ({len(ens_res)} methods)")
        except Exception as e: print(f"Failed: {e}")
        
    return base_results, [r for r in base_results if 'Ensemble' not in r['name']]
