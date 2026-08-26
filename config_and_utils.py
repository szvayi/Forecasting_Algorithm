import os
import random
import logging
import json
import warnings
import traceback
import datetime
from functools import lru_cache
import sys

def setup_logging(log_dir="logs"):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_filename = f"{log_dir}/forecast_run_{datetime.datetime.now().strftime('%Y%m%d')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info(f"Logging initialized. Log file: {log_filename}")
    return logging.getLogger(__name__)
from dataclasses import dataclass, field
from typing import Dict, List
import pandas as pd
import numpy as np
from scipy import stats
from scipy.signal import find_peaks
from statsmodels.tsa.stattools import adfuller, acf

# 尝试导入tensorflow，如果失败则设置为None
try:
    import tensorflow as tf
except ImportError:
    tf = None

# 尝试导入matplotlib，如果失败则设置为None
try:
    import matplotlib.pyplot as plt
    from matplotlib import rcParams
    from matplotlib.font_manager import FontProperties
    
    rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    rcParams['axes.unicode_minus'] = False
except ImportError:
    plt = None
    rcParams = None
    FontProperties = None

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
logging.getLogger('prophet').setLevel(logging.ERROR)
logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

DEBUG_MODE = False
PROPHET_VALID_PARAMS = {
    'changepoint_prior_scale', 'seasonality_prior_scale',
    'seasonality_mode', 'changepoint_range', 'n_changepoints',
}

def debug_print(*args, **kwargs):
    if DEBUG_MODE:
        print(*args, **kwargs)

def set_seeds(seed=42):
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    if tf is not None:
        tf.random.set_seed(seed)

set_seeds()

# 銆愪慨澶嶅锛氬幓鎺変簡鍓嶇紑鐨勪笅鍒掔嚎銆?
@lru_cache(maxsize=1)
def get_catboost_regressor():
    try:
        from catboost import CatBoostRegressor
        return CatBoostRegressor
    except ImportError:
        return None

class suppress_stdout_stderr:
    def __init__(self):
        self.null_fds = [os.open(os.devnull, os.O_RDWR) for _ in range(2)]
        self.save_fds = [os.dup(1), os.dup(2)]
    def __enter__(self):
        os.dup2(self.null_fds[0], 1)
        os.dup2(self.null_fds[1], 2)
    def __exit__(self, *_):
        os.dup2(self.save_fds[0], 1)
        os.dup2(self.save_fds[1], 2)
        for fd in self.null_fds + self.save_fds:
            os.close(fd)

def _mp_worker(func, q):
    import os
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
    # 设置Prophet环境变量，避免多进程问题
    os.environ['STAN_BACKEND'] = 'CMDSTANPY'
    os.environ['CMDSTANPY_COMPILE'] = 'false'
    try:
        res = func()
        q.put((True, res))
    except Exception as e:
        q.put((False, f"{str(e)}\n{traceback.format_exc()}"))

def run_with_timeout(func, timeout_seconds, default_return=None):
    import multiprocessing
    import queue
    ctx = multiprocessing.get_context('spawn')
    q = ctx.Queue()
    p = ctx.Process(target=_mp_worker, args=(func, q))
    p.start()
    p.join(timeout_seconds)

    if p.is_alive():
        p.terminate()
        p.join()
        # 返回带错误信息的字典
        return {'error': f'Timeout after {timeout_seconds}s', 'forecast': None, 'wmape': float('inf')}

    try:
        success, result = q.get_nowait()
        if success: return result
        else: 
            # 返回带错误信息的字典
            return {'error': result, 'forecast': None, 'wmape': float('inf')}
    except queue.Empty:
        return {'error': 'Empty result from worker', 'forecast': None, 'wmape': float('inf')}

def safe_predictions(preds, fallback_value, model_name=""):
    preds = np.asarray(preds).flatten().copy()
    nan_count = np.sum(np.isnan(preds))
    if nan_count > 0:
        preds = np.nan_to_num(preds, nan=fallback_value)
    inf_count = np.sum(np.isinf(preds))
    if inf_count > 0:
        preds = np.nan_to_num(preds, posinf=fallback_value, neginf=0)
    neg_count = np.sum(preds < 0)
    if neg_count > 0:
        preds = np.maximum(preds, 0)
    if np.all(preds == 0):
        preds = np.full_like(preds, fallback_value)
    return preds

def restore_volatility(predictions, historical_series, strength=0.5):
    preds = np.array(predictions).flatten().copy()
    hist_values = historical_series.values.flatten()
    hist_mean = np.mean(hist_values)
    hist_std = np.std(hist_values)
    hist_cv = hist_std / hist_mean if hist_mean > 0 else 0
    pred_mean = np.mean(preds)
    pred_std = np.std(preds)
    pred_cv = pred_std / pred_mean if pred_mean > 0 else 0

    if pred_cv < hist_cv * 0.5 and hist_cv > 0.05:
        period = min(52, len(hist_values) // 2)
        if len(hist_values) >= period:
            seasonal_pattern = extract_seasonal_pattern(historical_series, period)
            n_preds = len(preds)
            start_idx = len(hist_values) % period
            adjusted_preds = preds.copy()
            for i in range(n_preds):
                idx = (start_idx + i) % period
                if idx < len(seasonal_pattern):
                    seasonal_factor = seasonal_pattern[idx]
                    target_value = pred_mean * seasonal_factor
                    adjusted_preds[i] = (1 - strength) * preds[i] + strength * target_value
            preds = adjusted_preds

        new_std = np.std(preds)
        new_cv = new_std / np.mean(preds) if np.mean(preds) > 0 else 0
        if new_cv < hist_cv * 0.4:
            recent_weeks = min(16, len(hist_values))
            recent_data = hist_values[-recent_weeks:]
            recent_mean = np.mean(recent_data)
            if recent_mean > 0:
                relative_pattern = (recent_data - recent_mean) / recent_mean
                for i in range(len(preds)):
                    pattern_idx = i % len(relative_pattern)
                    adjustment = relative_pattern[pattern_idx] * pred_mean * strength * 0.5
                    preds[i] += adjustment
    preds = np.maximum(preds, 0)
    return preds

@dataclass
class SPUProfile:
    spu: str
    raw_samples: int = 0
    clean_samples: int = 0
    date_start: str = ""
    date_end: str = ""
    data_span_weeks: int = 0
    zero_count: int = 0
    zero_ratio: float = 0.0
    missing_count: int = 0
    missing_ratio: float = 0.0
    outlier_count: int = 0
    data_quality_score: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    cv: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    q25: float = 0.0
    q75: float = 0.0
    iqr: float = 0.0
    trend_direction: str = ""
    trend_strength: float = 0.0
    seasonality_detected: bool = False
    seasonality_period: int = 0
    is_stationary: bool = False
    adf_pvalue: float = 1.0
    autocorr_lag1: float = 0.0
    autocorr_lag4: float = 0.0
    seasonal_strength: float = 0.0
    seasonal_period: int = 52
    seasonal_pattern: List[float] = field(default_factory=list)
    train_samples: int = 0
    test_samples: int = 0
    train_date_range: str = ""
    test_date_range: str = ""
    exog_cols: List[str] = field(default_factory=list)
    exog_correlations: Dict[str, float] = field(default_factory=dict)
    model_results: List[Dict] = field(default_factory=list)
    winner_name: str = ""
    winner_wmape: float = 0.0
    total_time: float = 0.0
    forecast_mean: float = 0.0
    forecast_std: float = 0.0
    forecast_trend: str = ""
    forecast_change_pct: float = 0.0

class SPUProfiler:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def analyze(self, spu: str, series: pd.Series, original_series: pd.Series = None,
                exog_df: pd.DataFrame = None) -> SPUProfile:
        profile = SPUProfile(spu=spu)
        if original_series is None: original_series = series

        profile.raw_samples = len(original_series)
        profile.clean_samples = len(series)
        profile.date_start = str(series.index.min().date())
        profile.date_end = str(series.index.max().date())
        profile.data_span_weeks = len(series)

        profile.zero_count = int((original_series == 0).sum())
        profile.zero_ratio = profile.zero_count / len(original_series) if len(original_series) > 0 else 0
        profile.missing_count = int(original_series.isna().sum())
        profile.missing_ratio = profile.missing_count / len(original_series) if len(original_series) > 0 else 0

        Q1, Q3 = series.quantile(0.25), series.quantile(0.75)
        IQR = Q3 - Q1
        outlier_mask = (series < Q1 - 1.5 * IQR) | (series > Q3 + 1.5 * IQR)
        profile.outlier_count = int(outlier_mask.sum())

        quality_penalties = (profile.zero_ratio * 20 + profile.missing_ratio * 30 + 
                             (profile.outlier_count / len(series)) * 20 + max(0, (30 - len(series)) / 30) * 30)
        profile.data_quality_score = max(0, 100 - quality_penalties)

        profile.mean = float(series.mean())
        profile.median = float(series.median())
        profile.std = float(series.std())
        profile.min_val = float(series.min())
        profile.max_val = float(series.max())
        profile.cv = profile.std / profile.mean if profile.mean > 0 else 0
        profile.skewness = float(stats.skew(series.dropna()))
        profile.kurtosis = float(stats.kurtosis(series.dropna()))
        profile.q25 = float(Q1)
        profile.q75 = float(Q3)
        profile.iqr = float(IQR)

        self._analyze_time_series_features(series, profile)

        if exog_df is not None and len(exog_df) > 0:
            profile.exog_cols = list(exog_df.columns)
            for col in exog_df.columns:
                try:
                    corr = series.corr(exog_df[col])
                    profile.exog_correlations[col] = round(corr, 3) if not np.isnan(corr) else 0
                except:
                    profile.exog_correlations[col] = 0

        return profile

    def _analyze_time_series_features(self, series: pd.Series, profile: SPUProfile):
        try:
            strength, _, period = detect_seasonality_strength(series)
            profile.seasonal_strength = float(strength)
            profile.seasonal_period = int(period)
            pattern = extract_seasonal_pattern(series, period)
            profile.seasonal_pattern = list(pattern[:12])
        except: pass
        
        values = series.values.flatten()
        try:
            x = np.arange(len(values))
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, values)
            profile.trend_strength = abs(r_value)
            if abs(slope) < 0.01 * profile.mean or profile.trend_strength < 0.3:
                profile.trend_direction = "骞崇ǔ"
            elif slope > 0: profile.trend_direction = "涓婂崌"
            else: profile.trend_direction = "涓嬮檷"
        except:
            profile.trend_direction = "鏈煡"
            profile.trend_strength = 0

        try:
            if len(values) >= 20:
                adf_result = adfuller(values, autolag='AIC')
                profile.adf_pvalue = float(adf_result[1])
                profile.is_stationary = profile.adf_pvalue < 0.05
        except: pass

    def update_with_results(self, profile: SPUProfile, train_data: pd.Series, test_data: pd.Series,
                            model_results: List[Dict], winner: Dict, future_preds: np.ndarray, total_time: float):
        profile.train_samples = len(train_data)
        profile.test_samples = len(test_data)
        profile.train_date_range = f"{train_data.index.min().date()} ~ {train_data.index.max().date()}"
        profile.test_date_range = f"{test_data.index.min().date()} ~ {test_data.index.max().date()}"

        profile.model_results = [
            {'name': r['name'], 'wmape': round(r['wmape'], 4) if r['wmape'] < float('inf') else 999,
             'status': 'success' if r['forecast'] is not None else 'failed', 'error': r.get('error', None)}
            for r in model_results
        ]
        profile.winner_name = winner['name']
        profile.winner_wmape = winner['wmape']
        profile.total_time = total_time

        if future_preds is not None and len(future_preds) > 0:
            profile.forecast_mean = float(np.mean(future_preds))
            profile.forecast_std = float(np.std(future_preds))
            if len(future_preds) >= 2:
                first_half = np.mean(future_preds[:len(future_preds) // 2])
                second_half = np.mean(future_preds[len(future_preds) // 2:])
                change = (second_half - first_half) / first_half if first_half > 0 else 0
                if abs(change) < 0.05: profile.forecast_trend = "骞崇ǔ"
                elif change > 0: profile.forecast_trend = "涓婂崌"
                else: profile.forecast_trend = "涓嬮檷"
            if profile.mean > 0:
                profile.forecast_change_pct = (profile.forecast_mean - profile.mean) / profile.mean

        return profile

    def print_profile(self, profile: SPUProfile):
        quality_icon = "⭐" if profile.data_quality_score >= 80 else ("⚠️" if profile.data_quality_score >= 60 else "❌")
        print("\n" + "┌" + "─" * 68 + "┐")
        print(f"│{'SPU DATA PROFILE':^68}│")
        print("├" + "─" * 68 + "┤")
        print(f"│ 📂 SPU: {profile.spu:<59}│")
        print(f"│ 📅 时间: {profile.date_start} ~ {profile.date_end} ({profile.data_span_weeks}周){' ' * 15}│")
        print(f"│ 📊 质量: {quality_icon} {profile.data_quality_score:.1f}/100  样本: {profile.clean_samples}{' ' * 28}│")
        print(f"│ 📈 均值: {profile.mean:,.1f}  标准差: {profile.std:,.1f}  CV: {profile.cv:.2f}{' ' * 20}│")

        trend_icon = "📈" if profile.trend_direction == "上升" else ("📉" if profile.trend_direction == "下降" else "➡️")
        trend_strength_desc = "强" if profile.trend_strength > 0.5 else ("中" if profile.trend_strength > 0.2 else "弱")
        print(f"│ 🔍 趋势: {trend_icon} {profile.trend_direction} ({trend_strength_desc}, R²={profile.trend_strength:.2f}){' ' * 22}│")

        seasonal_icon = "🌙" if profile.seasonal_strength > 0.5 else ("🌓" if profile.seasonal_strength > 0.2 else "🌑")
        seasonal_level = "强" if profile.seasonal_strength > 0.5 else ("中" if profile.seasonal_strength > 0.2 else "弱")
        print(f"│ 🔁 季节: {seasonal_icon} {seasonal_level} (强度={profile.seasonal_strength:.2f}, 周期={profile.seasonal_period}){' ' * 18}│")
        print("└" + "─" * 68 + "┘")

    def print_model_competition(self, profile: SPUProfile):
        print("\n┌" + "─" * 60 + "┐")
        print(f"│{'MODEL COMPETITION':^60}│")
        print("├" + "─" * 60 + "┤")
        sorted_results = sorted(profile.model_results, key=lambda x: x['wmape'] if x['wmape'] < 999 else 999)
        for r in sorted_results:
            icon = "🏆" if r['name'] == profile.winner_name else "  "
            wmape_str = f"{r['wmape'] * 100:.2f}%" if r['wmape'] < 999 else "N/A"
            status = "✅" if r['status'] == 'success' else "❌"
            print(f"│ {icon}{r['name']:<25} {wmape_str:>10} {status:>5}{' ' * 12}│")
        print("├" + "─" * 60 + "┤")
        print(f"│ ⏳ Time: {profile.total_time:.1f}s  🏆 {profile.winner_name} ({profile.winner_wmape * 100:.2f}%){' ' * 5}│")
        print("└" + "─" * 60 + "┘")

    def print_forecast_summary(self, profile: SPUProfile, future_dates, future_preds):
        trend_icon = "📈" if profile.forecast_trend == "上升" else ("📉" if profile.forecast_trend == "下降" else "➡️")
        print("\n┌" + "─" * 60 + "┐")
        print(f"│{'FORECAST SUMMARY':^60}│")
        print("├" + "─" * 60 + "┤")
        print(f"│ 预测周期: {len(future_preds)}周 ({future_dates[0].date()} ~ {future_dates[-1].date()}){' ' * 8}│")
        print(f"│ 预测均值: {profile.forecast_mean:,.1f}  历史均值: {profile.mean:,.1f}{' ' * 18}│")
        print(f"│ 变化趋势: {trend_icon} {profile.forecast_trend} ({profile.forecast_change_pct * 100:+.1f}%){' ' * 26}│")
        print("└" + "─" * 60 + "┘")

    def generate_report_dict(self, profile: SPUProfile) -> Dict:
        return {'spu': profile.spu, 'samples': profile.clean_samples, 'quality_score': round(profile.data_quality_score, 2),
                'mean': round(profile.mean, 2), 'cv': round(profile.cv, 4), 'trend': profile.trend_direction,
                'winner': profile.winner_name, 'wmape': round(profile.winner_wmape, 4), 'time': round(profile.total_time, 2)}

class SearchConfig:
    FAST = {
        'prophet': {'changepoint_prior_scale': [0.05], 'seasonality_prior_scale': [10.0], 'seasonality_mode': ['additive']},
        'xgboost': {'n_estimators': [100], 'max_depth': [3], 'learning_rate': [0.1], 'subsample': [0.8], 'colsample_bytree': [0.8]},
        'lgbm': {'n_estimators': [100], 'num_leaves': [31], 'learning_rate': [0.1], 'subsample': [0.8], 'colsample_bytree': [0.8]},
        'catboost': {'iterations': [100], 'depth': [6], 'learning_rate': [0.1]},
        'dl_residual': {'look_back': [4], 'neurons': [32], 'epochs': 15, 'learning_rate': [0.01], 'dropout': [0.1]},
        'ensemble': {'methods': ['weighted']}, 'use_auto_arima': False, 'arima_order': (1, 1, 1),
        'arima_seasonal_order': (0, 1, 1, 52), 'model_timeout': 60, 'arima_timeout': 45, 'dl_timeout': 120,
        'enable_tcn': False, 'enable_nbeats': False, 'max_combinations': 8
    }
    SMART = {
        'prophet': {'changepoint_prior_scale': [0.01, 0.05, 0.15], 'seasonality_prior_scale': [1.0, 10.0], 'seasonality_mode': ['additive', 'multiplicative'], 'changepoint_range': [0.8, 0.9], 'n_changepoints': [15, 25]},
        'xgboost': {'n_estimators': [100, 200, 300], 'max_depth': [3, 5, 7], 'learning_rate': [0.03, 0.1], 'subsample': [0.7, 0.9], 'colsample_bytree': [0.7, 0.9], 'min_child_weight': [1, 3], 'reg_alpha': [0, 0.1], 'reg_lambda': [1, 2]},
        'lgbm': {'n_estimators': [100, 200, 300], 'num_leaves': [31, 50, 80], 'learning_rate': [0.03, 0.1], 'subsample': [0.7, 0.9], 'colsample_bytree': [0.7, 0.9], 'min_child_samples': [10, 20], 'reg_alpha': [0, 0.1], 'reg_lambda': [0, 1]},
        'catboost': {'iterations': [150, 300], 'depth': [4, 6, 8], 'learning_rate': [0.03, 0.1], 'l2_leaf_reg': [1, 3, 5]},
        'dl_residual': {'look_back': [4, 8, 12], 'neurons': [32, 64], 'epochs': 25, 'learning_rate': [0.005, 0.01], 'dropout': [0.1, 0.2]},
        'ensemble': {'methods': ['weighted', 'stacking']}, 'use_auto_arima': True, 'arima_max_p': 2, 'arima_max_q': 2,
        'model_timeout': 120, 'arima_timeout': 240, 'dl_timeout': 240, 'enable_tcn': True, 'enable_nbeats': True, 'max_combinations': 25
    }
    FULL = {
        'prophet': {'changepoint_prior_scale': [0.001, 0.01, 0.05, 0.1, 0.3], 'seasonality_prior_scale': [0.1, 1.0, 10.0], 'seasonality_mode': ['additive', 'multiplicative'], 'changepoint_range': [0.8, 0.9], 'n_changepoints': [15, 25, 35]},
        'xgboost': {'n_estimators': [100, 200, 300, 500], 'max_depth': [3, 5, 7, 9], 'learning_rate': [0.01, 0.05, 0.1], 'subsample': [0.6, 0.8, 1.0], 'colsample_bytree': [0.6, 0.8, 1.0], 'min_child_weight': [1, 3, 5], 'reg_alpha': [0, 0.1], 'reg_lambda': [1, 3]},
        'lgbm': {'n_estimators': [100, 200, 300, 500], 'num_leaves': [31, 50, 80, 120], 'learning_rate': [0.01, 0.05, 0.1], 'subsample': [0.6, 0.8, 1.0], 'colsample_bytree': [0.6, 0.8, 1.0], 'min_child_samples': [5, 10, 20], 'reg_alpha': [0, 0.1], 'reg_lambda': [0, 1, 3]},
        'catboost': {'iterations': [200, 400, 600], 'depth': [4, 6, 8], 'learning_rate': [0.01, 0.05, 0.1], 'l2_leaf_reg': [1, 3, 5]},
        'dl_residual': {'look_back': [4, 8, 12], 'neurons': [32, 64, 96], 'epochs': 30, 'learning_rate': [0.005, 0.01, 0.02], 'dropout': [0.1, 0.2, 0.3]},
        'ensemble': {'methods': ['simple', 'weighted', 'stacking']}, 'use_auto_arima': True, 'arima_max_p': 3, 'arima_max_q': 3,
        'model_timeout': 180, 'arima_timeout': 360, 'dl_timeout': 360, 'enable_tcn': True, 'enable_nbeats': True, 'max_combinations': 50
    }
    @classmethod
    def get(cls, mode='full'):
        if mode == 'fast': return cls.FAST
        elif mode == 'smart': return cls.SMART
        return cls.FULL

def calculate_wmape(y_true, y_pred):
    y_true, y_pred = np.asarray(y_true).flatten(), np.asarray(y_pred).flatten()
    total = np.sum(np.abs(y_true))
    return np.sum(np.abs(y_true - y_pred)) / total if total > 0 else float('inf')

def clean_params_for_db(params):
    if not params: return "{}"
    clean = {}
    for k, v in params.items():
        if isinstance(v, (list, np.ndarray)): clean[k] = str(v)
        elif 'model' in k or 'eng' in k or 'scaler' in k: continue
        elif isinstance(v, (int, float, str, bool, type(None))): clean[k] = v
        else: clean[k] = str(type(v).__name__)
    return json.dumps(clean, ensure_ascii=False, default=str)

def get_current_week_end():
    today = pd.Timestamp.today().normalize()
    return today + pd.Timedelta(days=(6 - today.dayofweek) % 7)


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

def make_log_diff(series):
    values = np.maximum(series.values.flatten(), 0)
    log_series = np.log1p(values)
    diff_series = pd.Series(np.diff(log_series), index=series.index[1:])
    return diff_series, log_series[-1]

def reconstruct_from_log_diff(last_log_val, diff_preds):
    diff_preds = np.nan_to_num(diff_preds, nan=0.0, posinf=0.0, neginf=0.0)
    reconstructed_log = np.clip(last_log_val + np.cumsum(diff_preds), -20, 20)
    return np.maximum(np.expm1(reconstructed_log), 0)

def clean_series(series, zero_handling='interpolate'):
    if zero_handling == 'interpolate': return series.replace(0, np.nan).interpolate().bfill().ffill()
    return series.fillna(0)

def detect_seasonality_strength(series, period=52):
    values = series.values.flatten() if hasattr(series, 'values') else np.array(series)
    n = len(values)
    if n < period * 1.5:
        try:
            acf_vals = acf(values, nlags=min(period, n - 1), fft=False)
            best_period, max_acf = period, 0
            for p in [4, 12, 13, 26, 52]:
                if p < len(acf_vals) and abs(acf_vals[p]) > max_acf:
                    max_acf, best_period = abs(acf_vals[p]), p
            return max_acf, None, best_period
        except: return 0.0, None, period
    try:
        from statsmodels.tsa.seasonal import STL
        result = STL(values, period=min(period, n // 2), robust=True).fit()
        var_detrend = np.var(values - result.trend)
        strength = max(0, min(1, 1 - np.var(result.resid) / var_detrend)) if var_detrend > 0 else 0
        return strength, result.seasonal, period
    except: return _fft_seasonality_detection(values, period)

def _fft_seasonality_detection(values, expected_period=52):
    from scipy.fft import fft
    n = len(values)
    detrended = values - np.linspace(values[0], values[-1], n)
    fft_vals, freqs = np.abs(fft(detrended))[:n // 2], np.fft.fftfreq(n)[:n // 2]
    peaks, _ = find_peaks(fft_vals, height=np.mean(fft_vals))
    if len(peaks) == 0: return 0.0, None, expected_period
    strongest_peak = peaks[np.argmax(fft_vals[peaks])]
    detected_period = int(1 / freqs[strongest_peak]) if freqs[strongest_peak] > 0 else expected_period
    strength = (fft_vals[strongest_peak] ** 2) / np.sum(fft_vals ** 2) if np.sum(fft_vals ** 2) > 0 else 0
    return min(1, strength * 5), None, detected_period

def extract_seasonal_pattern(series, period=52):
    values = series.values.flatten() if hasattr(series, 'values') else np.array(series)
    if len(values) < period: return np.ones(period)
    pattern = np.array([np.mean(values[i::period]) for i in range(period)], dtype=float)
    return pattern / float(np.mean(pattern)) if float(np.mean(pattern)) > 0 else np.ones(period)

def extract_seasonal_factors_52week(series, period=52):
    """
    鎻愬彇 52 鍛ㄥ鑺傚懆鏈熺殑瀛ｈ妭鍥犲瓙锛圝SON 鏍煎紡锛?
    
    鍙傛暟锛?
        series: 娓呮礂鍚庣殑鍛ㄩ攢閲?Series
        period: 鍛ㄦ湡锛堥粯璁?52 鍛級
    
    杩斿洖锛?
        seasonal_json (str): JSON 瀛楃涓诧紝key 涓?week_1~week_52锛寁alue 涓哄鑺傚洜瀛愶紙0.5~1.5鑼冨洿锛?
    """
    try:
        if len(series) < period:
            # 鏁版嵁涓嶈冻涓€涓畬鏁村懆鏈燂紝杩斿洖鍧囧寑鍥犲瓙
            return json.dumps({f"week_{i+1}": 1.0 for i in range(period)}, ensure_ascii=False)
        
        # 澶氬懆鏈熸埅鏂細鍙敤鏈€杩?2-3 涓畬鏁村懆鏈熻绠楋紙鏇磋创杩戝綋鍓嶈秼鍔匡級
        recent_cycles = min(3, len(series) // period)
        if recent_cycles < 1:
            recent_cycles = 1
        
        recent_len = recent_cycles * period
        recent_series = series.iloc[-recent_len:].values
        
        # 鍒嗚В鎴愬涓懆鏈?
        cycles = [recent_series[i*period:(i+1)*period] for i in range(recent_cycles)]
        
        # 璁＄畻姣忎釜鍛ㄤ綅缃殑骞冲潎鍊?
        seasonal_pattern = np.zeros(period)
        for week_idx in range(period):
            week_values = [cycle[week_idx] for cycle in cycles if week_idx < len(cycle)]
            seasonal_pattern[week_idx] = np.mean(week_values) if len(week_values) > 0 else 1.0
        
        # 褰掍竴鍖栵細鍧囧€间负 1锛堣繖鏍峰鑺傚洜瀛?脳 骞冲潎鍊?鈮?鍘熷鍊硷級
        pattern_mean = np.mean(seasonal_pattern)
        if pattern_mean > 0:
            seasonal_pattern = seasonal_pattern / pattern_mean
        else:
            seasonal_pattern = np.ones(period)
        
        # 骞虫粦锛氶伩鍏嶅崟鍛ㄦ尝鍔ㄨ繃澶?
        seasonal_pattern = pd.Series(seasonal_pattern).rolling(window=3, center=True, min_periods=1).mean().values
        
        # 闄愬埗鍥犲瓙鑼冨洿锛?.5~1.5
        seasonal_pattern = np.clip(seasonal_pattern, 0.5, 1.5)
        
        # 鐢熸垚 JSON
        seasonal_json = {
            f"week_{i+1}": round(float(seasonal_pattern[i]), 4)
            for i in range(period)
        }
        
        return json.dumps(seasonal_json, ensure_ascii=False)
    
    except Exception as e:
        print(f"   鈿狅笍 瀛ｈ妭鍥犲瓙鎻愬彇澶辫触: {e}锛岃繑鍥為粯璁ゅ潎鍖€鍥犲瓙")
        return json.dumps({f"week_{i+1}": 1.0 for i in range(period)}, ensure_ascii=False)


def detect_trend_strength(series):
    values = series.values.flatten() if hasattr(series, 'values') else np.array(series)
    if len(values) < 5: return 'flat', 0.0, 0.0
    try:
        slope, intercept, r_value, _, _ = stats.linregress(np.arange(len(values)), values)
        trend_strength, mean_val = r_value ** 2, np.mean(values)
        normalized_slope = slope / mean_val if mean_val > 0 else slope
        if abs(normalized_slope) < 0.005 or trend_strength < 0.1: trend_direction = 'flat'
        elif slope > 0: trend_direction = 'up'
        else: trend_direction = 'down'
        return trend_direction, float(trend_strength), float(normalized_slope)
    except: return 'flat', 0.0, 0.0

def calculate_trend_consistency(predictions, expected_direction, expected_slope):
    preds = np.array(predictions).flatten()
    if len(preds) < 2: return 0.5
    try:
        pred_slope, _, _, _, _ = stats.linregress(np.arange(len(preds)), preds)
        pred_normalized_slope = pred_slope / np.mean(preds) if np.mean(preds) > 0 else pred_slope
        
        if expected_direction == 'up': direction_score = 1.0 if pred_slope > 0 else 0.0
        elif expected_direction == 'down': direction_score = 1.0 if pred_slope < 0 else 0.0
        else: direction_score = np.exp(-abs(pred_normalized_slope) * 10)
        
        slope_score = 0.5
        if expected_direction != 'flat' and abs(expected_slope) > 0.001:
            slope_score = np.exp(-abs(pred_normalized_slope / expected_slope - 1) * 2) if expected_slope != 0 else 0.5
            
        return max(0.0, min(1.0, 0.7 * direction_score + 0.3 * slope_score))
    except: return 0.5

def extrapolate_trend(historical_series, n_future, trend_strength, trend_direction):
    values = historical_series.values.flatten() if hasattr(historical_series, 'values') else np.array(historical_series)
    if trend_direction == 'flat' or trend_strength < 0.1: return np.zeros(n_future)
    recent_n = min(20, len(values))
    try:
        slope, _, _, _, _ = stats.linregress(np.arange(recent_n), values[-recent_n:])
        return slope * np.arange(1, n_future + 1) * np.exp(-np.arange(n_future) * 0.02 * (1 - trend_strength))
    except: return np.zeros(n_future)

def get_seasonal_indices(future_dates, series_end_date, period=52):
    base_week = series_end_date.isocalendar()[1] if hasattr(series_end_date, 'isocalendar') else pd.Timestamp(series_end_date).isocalendar()[1]
    return (base_week + (np.arange(1, len(future_dates) + 1) % period) - 1) % period

def plot_forecast(profile, train_data, test_data, all_results, future_preds, future_dates, save_path=None, show_plot=True):
    try:
        fig, axes = plt.subplots(2, 1, figsize=(14, 10))
        ax = axes[0]
        ax.plot(train_data.index, train_data.values, label='历史数据', color='#333', linewidth=1.5)
        ax.plot(test_data.index, test_data.values, label='实际值', color='black', marker='o', linewidth=2)
        colors = plt.cm.tab10(np.linspace(0, 1, len(all_results)))
        for idx, res in enumerate(all_results):
            is_winner = res['name'] == profile.winner_name
            ax.plot(test_data.index, res['forecast'], linestyle='-' if is_winner else '--',
                    alpha=1.0 if is_winner else 0.4, linewidth=2.5 if is_winner else 1.0,
                    color='red' if is_winner else colors[idx], label=res['name'])
        ax.plot(future_dates, future_preds, label='未来预测', color='purple', linewidth=3, marker='D', markersize=5)
        ax.set_title(f"SPU: {profile.spu} - 🏆 {profile.winner_name} (WMAPE: {profile.winner_wmape:.2%})", fontsize=14, fontweight='bold')
        ax.legend(loc='upper left', ncol=3, fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('日期', fontsize=11); ax.set_ylabel('销售量', fontsize=11)

        ax2 = axes[1]
        sorted_res = sorted(all_results, key=lambda x: x['wmape'])
        names = [r['name'][:15] for r in sorted_res]
        wmapes = [r['wmape'] * 100 for r in sorted_res]
        colors_bar = ['gold' if r['name'] == profile.winner_name else 'steelblue' for r in sorted_res]
        bars = ax2.barh(names, wmapes, color=colors_bar, edgecolor='black')
        for bar in bars:
            ax2.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2, f'{bar.get_width():.2f}%', va='center', fontsize=9)
        ax2.set_xlabel("WMAPE (%)", fontsize=11); ax2.set_title("模型性能对比", fontsize=12)
        ax2.invert_yaxis(); plt.tight_layout()

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            plt.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='white')
        if show_plot: plt.show()
        else: plt.close(fig)
    except Exception as e: print(f"   ⚠️ 绘图失败: {str(e)}")

def plot_best_spu_style(profile, train_data, test_data, all_results, future_preds, future_dates, sku_future_df=None, save_path=None, show_plot=True, top_n_skus=5, color_palette=None):
    """绘制 SPU 级预测与 SKU 级预测的联合图表"""
    try:
        # 尝试加载自定义字体
        font_path = os.path.join('static', 'file-ngwyeoEN29l1M3O1QpdxCwkj-sider-font.ttf')
        if os.path.exists(font_path):
            font_prop = FontProperties(fname=font_path)
            # 注意：这可能会覆盖全局字体设置，如果需要仅对特定文本应用，需要传递 fontproperties 参数
            # 但为了简化，这里尝试设置全局字体族，或者如果失败，matplotlib 会回退
            try:
                plt.rcParams['font.family'] = font_prop.get_name()
            except:
                pass 
        
        top_results = sorted(all_results, key=lambda x: x['wmape'])[:4]
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), gridspec_kw={'height_ratios': [2.5, 1]})
        
        # 历史数据和实际值
        ax1.plot(train_data.index, train_data.values, label='历史数据', color='#666666', linewidth=2, marker='.', markersize=6)
        ax1.plot(test_data.index, test_data.values, label='实际值', color='black', linewidth=2.5, marker='o', markersize=8, zorder=10)
        
        # SPU 级模型预测
        default_colors = ['#FF9F40', '#4BC0C0', '#36A2EB', '#FF6384']
        colors = color_palette if color_palette else default_colors
        markers = ['^', 's', 'v', 'D']
        
        for i, res in enumerate(top_results):
            is_w = res['name'] == profile.winner_name
            color = colors[i % len(colors)]
            marker = markers[i % len(markers)]
            ax1.plot(test_data.index, res['forecast'], label=f"{res['name']} ({res['wmape']*100:.2f}%)",
                     linestyle='--', linewidth=3 if is_w else 2, color=color, marker=marker, markersize=7)
        
        # SPU 未来预测
        ax1.plot(future_dates, future_preds, label=f'未来预测 ({profile.winner_name})', 
                color='#9966FF', linewidth=3, marker='D', markersize=8, zorder=10)
        
        # 📦 SKU 级预测（如果提供了数据）
        if sku_future_df is not None and not sku_future_df.empty:
            top_skus = sku_future_df.sum().nlargest(top_n_skus).index  # 使用参数化的 top_n_skus
            sku_colors = plt.cm.Set3(np.linspace(0, 1, len(top_skus)))
            for idx, sku in enumerate(top_skus):
                ax1.plot(future_dates, sku_future_df[sku].values, 
                        label=f'SKU {sku}', linestyle=':', linewidth=1.5, 
                        color=sku_colors[idx], alpha=0.8, marker='o', markersize=3)
        
        # 区间标记
        ax1.axvspan(test_data.index[0], test_data.index[-1], color='yellow', alpha=0.15, label='验证区间')
        ax1.axvspan(future_dates[0], future_dates[-1], color='green', alpha=0.15, label='预测区间')
        
        ax1.set_title(f"SPU: {profile.spu} - 销售预测对比（含SKU拆分）\n🏆 胜出模型: {profile.winner_name} (WMAPE: {profile.winner_wmape:.2%})", 
                     fontsize=16, fontweight='bold', pad=20)
        ax1.grid(True, linestyle='--', alpha=0.5)
        ax1.legend(loc='upper left', ncol=2, fontsize=9, shadow=True)
        ax1.set_ylabel('销售量', fontsize=11)
        
        # WMAPE 对比柱状图
        names, wmapes = [r['name'] for r in top_results], [r['wmape'] * 100 for r in top_results]
        bars = ax2.bar(names, wmapes, color=colors[:len(top_results)], edgecolor='black', alpha=0.9, width=0.6)
        w_idx = next((i for i, r in enumerate(top_results) if r['name'] == profile.winner_name), 0)
        bars[w_idx].set_edgecolor('gold')
        bars[w_idx].set_linewidth(3)
        for b in bars:
            ax2.text(b.get_x() + b.get_width()/2., b.get_height()+0.5, f'{b.get_height():.2f}%', 
                    ha='center', va='bottom', fontsize=12, fontweight='bold')
        
        ax2.set_title("各模型 WMAPE 对比", fontsize=14)
        ax2.set_ylim(0, max(wmapes)*1.3)
        ax2.set_ylabel('WMAPE (%)', fontsize=11)
        ax2.grid(axis='y', linestyle='--', alpha=0.5)
        plt.tight_layout()
        
        if save_path:
            os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
            plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='white')
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
    except Exception as e:
        print(f"   ⚠️ 高级图表失败: {str(e)}")


def _calculate_group_dynamic_shares(df_spu_idx, group_col, spu_sales_weekly, future_dates):
    grouped_sales = df_spu_idx.groupby([pd.Grouper(freq='W'), group_col])['sales'].sum().unstack(fill_value=0)
    grouped_sales = grouped_sales.reindex(spu_sales_weekly.index, fill_value=0)

    total = grouped_sales.sum(axis=1)
    hist_shares = grouped_sales.div(total.replace(0, np.nan), axis=0).ffill().fillna(0)

    future_shares = {}
    LOOKBACK_WEEKS = 12
    MIN_WEEKS = 4
    DAMPING_FACTOR = 0.9

    for sku in hist_shares.columns:
        series = hist_shares[sku]
        n = len(series)

        if n >= MIN_WEEKS:
            window_size = min(n, LOOKBACK_WEEKS)
            recent_data = series.iloc[-window_size:]
            current_level = recent_data.ewm(span=window_size, adjust=False).mean().iloc[-1]

            try:
                x = np.arange(window_size)
                y = recent_data.values
                slope, intercept = np.polyfit(x, y, 1)
            except:
                slope = 0

            future_vals = []
            curr_val = current_level
            curr_slope = slope

            for _ in range(len(future_dates)):
                curr_val += curr_slope
                curr_slope *= DAMPING_FACTOR
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
    """
    SKU 份额预测（保留原函数签名，兼容现有调用）。
    """
    return _calculate_group_dynamic_shares(df_spu_idx, "sku", spu_sales_weekly, future_dates)


def calculate_principal_dynamic_shares(df_spu_idx, spu_sales_weekly, future_dates):
    """
    负责人（principal_names）权重预测。
    """
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
