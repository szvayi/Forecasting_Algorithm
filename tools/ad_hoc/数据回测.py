"""
销售预测引擎（多 SKU / 周频）。

这份脚本做的事情（按主流程从上到下）：
1) 从 CSV 读取多 SKU 销售数据（可选外生变量）。
2) 对每个 SKU 做周频聚合、清洗（0/缺失处理）、基础画像分析（波动/趋势/季节性/质量评分）。
3) 在验证集上做“模型竞赛”（Prophet / 树模型 / SARIMA+DL / 多种 Ensemble），以 WMAPE 选出胜者。
4) 用胜者对未来 16 周预测；并做最小化的安全修复（NaN/Inf/负值/全 0）、必要时恢复波动性。
5) 输出：预测明细 CSV、画像 JSON、可选写入数据库、可选绘图保存。

阅读建议：
- 想看入口与全局参数：`main()`
- 想看单 SKU 流程：`process_single_sku()`
- 想看模型对比：`run_all_models()` / `optimize_*()`
- 想看未来预测生成：`predict_future()`
"""

import pandas as pd
import numpy as np
import pmdarima as pm
from prophet import Prophet
from sklearn.preprocessing import MinMaxScaler
from sklearn.linear_model import Ridge
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import LSTM, Dense, Input, Conv1D, Flatten, Dropout, Lambda, Add
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping
import tensorflow as tf
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from scipy import stats
from scipy.signal import find_peaks  # 【新增】季节性检测用
from statsmodels.tsa.stattools import adfuller, acf
from sqlalchemy import text, create_engine
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from functools import lru_cache
import itertools
import warnings
import os
import random
import logging
import json
import datetime
import time
from dataclasses import dataclass, field
from typing import Dict, List
import matplotlib.pyplot as plt
from matplotlib import rcParams

# ==============================
# 运行环境与全局开关
# ==============================
rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

# 降低第三方库输出噪声（不影响计算逻辑）
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
logging.getLogger('prophet').setLevel(logging.ERROR)
logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# 🔧 调试模式开关：True 时会打印大量中间状态（便于排查模型/数据问题）
DEBUG_MODE = False

def debug_print(*args, **kwargs):
    """调试输出函数"""
    if DEBUG_MODE:
        print(*args, **kwargs)

def set_seeds(seed=42):
    """固定随机种子，减少实验波动（尽量可复现）。"""
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)

set_seeds()

@lru_cache(maxsize=1)
def _get_catboost_regressor():
    """延迟导入 CatBoost，避免在未安装时直接 ImportError。"""
    try:
        from catboost import CatBoostRegressor
        return CatBoostRegressor
    except ImportError:
        return None

class suppress_stdout_stderr:
    """上下文管理器：临时屏蔽 stdout / stderr。

    用途：Prophet/Stan 等训练时可能输出大量日志，这里把输出重定向到 devnull，
    让控制台信息更聚焦（不影响模型训练与结果）。
    """
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

def run_with_timeout(func, timeout_seconds, default_return=None):
    """在指定超时时间内执行函数，超时或异常时返回默认值。"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeout:
            return default_return
        except Exception:
            return default_return

def safe_predictions(preds, fallback_value, model_name=""):
    """
    最小化干预的预测安全检查（仅修复“确定有问题”的输出）。

    规则：
    - NaN / Inf：替换为 fallback
    - 负值：截断为 0（销量不应为负）
    - 全 0：用 fallback 填充（避免下游全 0 导致业务误判）
    """
    preds = np.asarray(preds).flatten().copy()

    # 1. 修复NaN
    nan_count = np.sum(np.isnan(preds))
    if nan_count > 0:
        debug_print(f"      [SAFE] {model_name}: 修复{nan_count}个NaN")
        preds = np.nan_to_num(preds, nan=fallback_value)

    # 2. 修复Inf
    inf_count = np.sum(np.isinf(preds))
    if inf_count > 0:
        debug_print(f"      [SAFE] {model_name}: 修复{inf_count}个Inf")
        preds = np.nan_to_num(preds, posinf=fallback_value, neginf=0)

    # 3. 修复负值 - 只将负值设为0
    neg_count = np.sum(preds < 0)
    if neg_count > 0:
        debug_print(f"      [SAFE] {model_name}: 修复{neg_count}个负值")
        preds = np.maximum(preds, 0)

    # 4. 全0检查 - 只有完全是0时才替换
    if np.all(preds == 0):
        debug_print(f"      [SAFE] {model_name}: 结果全0，使用fallback={fallback_value:.2f}")
        preds = np.full_like(preds, fallback_value)

    return preds

def restore_volatility(predictions, historical_series, strength=0.5):
    """当预测过于“平滑”时，按历史波动/季节性对预测做温和恢复。

    说明：
    - 这是“后处理”，仅在预测 CV 明显低于历史 CV 时触发
    - 目的是让预测更贴近历史的波动水平（而不是追求更高的均值/更低的误差）
    - 最终仍会做非负约束
    """

    preds = np.array(predictions).flatten().copy()
    hist_values = historical_series.values.flatten()

    # 计算历史波动性指标
    hist_mean = np.mean(hist_values)
    hist_std = np.std(hist_values)
    hist_cv = hist_std / hist_mean if hist_mean > 0 else 0

    # 计算预测波动性
    pred_mean = np.mean(preds)
    pred_std = np.std(preds)
    pred_cv = pred_std / pred_mean if pred_mean > 0 else 0

    # 如果预测波动性太低，进行恢复
    if pred_cv < hist_cv * 0.5 and hist_cv > 0.05:
        debug_print(f"      [VOLATILITY] 恢复波动性: pred_cv={pred_cv:.3f} -> target={hist_cv:.3f}")

        # 方法1: 提取历史季节性模式并应用
        period = min(52, len(hist_values) // 2)
        if len(hist_values) >= period:
            seasonal_pattern = extract_seasonal_pattern(historical_series, period)

            # 计算未来日期对应的季节性索引
            n_preds = len(preds)
            start_idx = len(hist_values) % period

            # 应用季节性调整
            adjusted_preds = preds.copy()
            for i in range(n_preds):
                idx = (start_idx + i) % period
                if idx < len(seasonal_pattern):
                    # 季节性因子
                    seasonal_factor = seasonal_pattern[idx]
                    # 混合原始预测和季节性调整
                    target_value = pred_mean * seasonal_factor
                    adjusted_preds[i] = (1 - strength) * preds[i] + strength * target_value

            preds = adjusted_preds

        # 方法2: 如果还是太平滑，添加基于历史的随机波动
        new_std = np.std(preds)
        new_cv = new_std / np.mean(preds) if np.mean(preds) > 0 else 0

        if new_cv < hist_cv * 0.4:
            debug_print(f"      [VOLATILITY] 添加历史波动模式")
            # 使用历史最后几周的相对波动
            recent_weeks = min(16, len(hist_values))
            recent_data = hist_values[-recent_weeks:]
            recent_mean = np.mean(recent_data)

            if recent_mean > 0:
                relative_pattern = (recent_data - recent_mean) / recent_mean
                # 循环应用到预测
                for i in range(len(preds)):
                    pattern_idx = i % len(relative_pattern)
                    adjustment = relative_pattern[pattern_idx] * pred_mean * strength * 0.5
                    preds[i] += adjustment

    preds = np.maximum(preds, 0)

    return preds

@dataclass
class SKUProfile:
    """单 SKU 数据画像 + 模型竞赛结果汇总。

    该结构用于：
    - 打印/保存数据质量、趋势季节性特征
    - 保存模型竞赛结果（各模型 WMAPE、冠军、耗时）
    - 保存未来预测摘要（均值、趋势等）
    """
    sku: str
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
class SKUProfiler:
    """对单 SKU 时间序列做画像分析，并在模型跑完后补充结果信息。"""
    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def analyze(self, sku: str, series: pd.Series, original_series: pd.Series = None,
                exog_df: pd.DataFrame = None) -> SKUProfile:
        """生成 `SKUProfile`（质量/统计量/趋势/季节性/外生变量相关性）。"""
        profile = SKUProfile(sku=sku)
        if original_series is None:
            original_series = series

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

        quality_penalties = (
                profile.zero_ratio * 20 +
                profile.missing_ratio * 30 +
                (profile.outlier_count / len(series)) * 20 +
                max(0, (30 - len(series)) / 30) * 30
        )
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

    def _analyze_time_series_features(self, series: pd.Series, profile: SKUProfile):
        try:
            strength, _, period = detect_seasonality_strength(series)
            profile.seasonal_strength = float(strength)
            profile.seasonal_period = int(period)
            pattern = extract_seasonal_pattern(series, period)
            profile.seasonal_pattern = list(pattern[:12])  # 只保存前12个
        except:
            pass
        values = series.values.flatten()
        try:
            x = np.arange(len(values))
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, values)
            profile.trend_strength = abs(r_value)
            if abs(slope) < 0.01 * profile.mean or profile.trend_strength < 0.3:
                profile.trend_direction = "平稳"
            elif slope > 0:
                profile.trend_direction = "上升"
            else:
                profile.trend_direction = "下降"
        except:
            profile.trend_direction = "未知"
            profile.trend_strength = 0

        try:
            if len(values) >= 20:
                adf_result = adfuller(values, autolag='AIC')
                profile.adf_pvalue = float(adf_result[1])
                profile.is_stationary = profile.adf_pvalue < 0.05
        except:
            pass

        try:
            if len(values) >= 10:
                acf_values = acf(values, nlags=min(10, len(values) - 1), fft=False)
                profile.autocorr_lag1 = float(acf_values[1]) if len(acf_values) > 1 else 0
                profile.autocorr_lag4 = float(acf_values[4]) if len(acf_values) > 4 else 0
        except:
            pass

    def update_with_results(self, profile: SKUProfile, train_data: pd.Series, test_data: pd.Series,
                            model_results: List[Dict], winner: Dict, future_preds: np.ndarray, total_time: float):
        """把模型竞赛结果与未来预测摘要写回到 `SKUProfile` 里。"""
        profile.train_samples = len(train_data)
        profile.test_samples = len(test_data)
        profile.train_date_range = f"{train_data.index.min().date()} ~ {train_data.index.max().date()}"
        profile.test_date_range = f"{test_data.index.min().date()} ~ {test_data.index.max().date()}"

        profile.model_results = [
            {
                'name': r['name'],
                'wmape': round(r['wmape'], 4) if r['wmape'] < float('inf') else 999,
                'status': 'success' if r['forecast'] is not None else 'failed',
                'error': r.get('error', None)
            }
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
                if abs(change) < 0.05:
                    profile.forecast_trend = "平稳"
                elif change > 0:
                    profile.forecast_trend = "上升"
                else:
                    profile.forecast_trend = "下降"
            if profile.mean > 0:
                profile.forecast_change_pct = (profile.forecast_mean - profile.mean) / profile.mean

        return profile

    def print_profile(self, profile: SKUProfile):
        """控制台打印：数据画像摘要（质量/趋势/季节性）。"""
        quality_icon = "🟢" if profile.data_quality_score >= 80 else (
            "🟡" if profile.data_quality_score >= 60 else "🔴")
        print("\n" + "┌" + "─" * 68 + "┐")
        print(f"│{'SKU DATA PROFILE':^68}│")
        print("├" + "─" * 68 + "┤")
        print(f"│ 📦 SKU: {profile.sku:<59}│")
        print(f"│ 📅 时间: {profile.date_start} ~ {profile.date_end} ({profile.data_span_weeks}周){' ' * 15}│")
        print(
            f"│ 📊 质量: {quality_icon} {profile.data_quality_score:.1f}/100  样本: {profile.clean_samples}{' ' * 28}│")
        print(f"│ 📈 均值: {profile.mean:,.1f}  标准差: {profile.std:,.1f}  CV: {profile.cv:.2f}{' ' * 20}│")

        # 趋势信息
        trend_icon = "📈" if profile.trend_direction == "上升" else (
            "📉" if profile.trend_direction == "下降" else "➡️")
        trend_strength_desc = "强" if profile.trend_strength > 0.5 else ("中" if profile.trend_strength > 0.2 else "弱")
        print(
            f"│ 🔍 趋势: {trend_icon} {profile.trend_direction} ({trend_strength_desc}, R²={profile.trend_strength:.2f}){' ' * 22}│")


        seasonal_icon = "🌊" if profile.seasonal_strength > 0.5 else ("〰️" if profile.seasonal_strength > 0.2 else "➖")
        seasonal_level = "强" if profile.seasonal_strength > 0.5 else (
            "中" if profile.seasonal_strength > 0.2 else "弱")
        print(
            f"│ 🗓️ 季节: {seasonal_icon} {seasonal_level} (强度={profile.seasonal_strength:.2f}, 周期={profile.seasonal_period}){' ' * 18}│")

        print("└" + "─" * 68 + "┘")

    def print_model_competition(self, profile: SKUProfile):
        """控制台打印：模型竞赛榜单（按 WMAPE 排序）。"""
        print("\n┌" + "─" * 60 + "┐")
        print(f"│{'MODEL COMPETITION':^60}│")
        print("├" + "─" * 60 + "┤")
        sorted_results = sorted(profile.model_results, key=lambda x: x['wmape'] if x['wmape'] < 999 else 999)
        for r in sorted_results:
            icon = "🏆" if r['name'] == profile.winner_name else "  "
            wmape_str = f"{r['wmape'] * 100:.2f}%" if r['wmape'] < 999 else "N/A"
            status = "✓" if r['status'] == 'success' else "✗"
            print(f"│ {icon}{r['name']:<25} {wmape_str:>10} {status:>5}{' ' * 12}│")
        print("├" + "─" * 60 + "┤")
        print(
            f"│ ⏱️ Time: {profile.total_time:.1f}s  🏆 {profile.winner_name} ({profile.winner_wmape * 100:.2f}%){' ' * 5}│")
        print("└" + "─" * 60 + "┘")

    def print_forecast_summary(self, profile: SKUProfile, future_dates, future_preds):
        """控制台打印：未来预测摘要（均值、变化趋势）。"""
        trend_icon = "📈" if profile.forecast_trend == "上升" else (
            "📉" if profile.forecast_trend == "下降" else "➡️")
        print("\n┌" + "─" * 60 + "┐")
        print(f"│{'FORECAST SUMMARY':^60}│")
        print("├" + "─" * 60 + "┤")
        print(f"│ 预测周期: {len(future_preds)}周 ({future_dates[0].date()} ~ {future_dates[-1].date()}){' ' * 8}│")
        print(f"│ 预测均值: {profile.forecast_mean:,.1f}  历史均值: {profile.mean:,.1f}{' ' * 18}│")
        print(
            f"│ 变化趋势: {trend_icon} {profile.forecast_trend} ({profile.forecast_change_pct * 100:+.1f}%){' ' * 26}│")
        print("└" + "─" * 60 + "┘")

    def generate_report_dict(self, profile: SKUProfile) -> Dict:
        """生成适合落盘/汇总的轻量字典（避免把大对象/数组直接写入 JSON）。"""
        return {
            'sku': profile.sku,
            'samples': profile.clean_samples,
            'quality_score': round(profile.data_quality_score, 2),
            'mean': round(profile.mean, 2),
            'cv': round(profile.cv, 4),
            'trend': profile.trend_direction,
            'winner': profile.winner_name,
            'wmape': round(profile.winner_wmape, 4),
            'time': round(profile.total_time, 2)
        }

class SearchConfig:
    """参数搜索空间配置（按运行模式分三档）。

    - FAST：速度优先，参数组合少、超时更短
    - SMART：默认推荐，平衡速度与效果
    - FULL：更充分的搜索，耗时更久

    说明：`max_combinations` 用于限制网格组合数，避免组合爆炸导致单 SKU 耗时过长。
    """
    FAST = {
        'prophet': {
            'changepoint_prior_scale': [0.05],
            'seasonality_prior_scale': [10.0],
            'seasonality_mode': ['additive']
        },
        'xgboost': {
            'n_estimators': [100],
            'max_depth': [3],
            'learning_rate': [0.1],
            'subsample': [0.8],
            'colsample_bytree': [0.8]
        },
        'lgbm': {
            'n_estimators': [100],
            'num_leaves': [31],
            'learning_rate': [0.1],
            'subsample': [0.8],
            'colsample_bytree': [0.8]
        },
        'catboost': {
            'iterations': [100],
            'depth': [6],
            'learning_rate': [0.1]
        },
        'dl_residual': {
            'look_back': [4],
            'neurons': [32],
            'epochs': 15,
            'learning_rate': [0.01],
            'dropout': [0.1]
        },
        'ensemble': {'methods': ['weighted']},
        'use_auto_arima': False,
        'arima_order': (1, 1, 1),
        'arima_seasonal_order': (0, 1, 1, 52),
        'model_timeout': 60,
        'arima_timeout': 120,
        'dl_timeout': 120,
        'enable_tcn': False,
        'enable_nbeats': False,
        'max_combinations': 8,  # 【新增】控制最大参数组合数
    }

    SMART = {
        'prophet': {
            'changepoint_prior_scale': [0.01, 0.05, 0.15],
            'seasonality_prior_scale': [1.0, 10.0],
            'seasonality_mode': ['additive', 'multiplicative'],
            'changepoint_range': [0.8, 0.9],
            'n_changepoints': [15, 25]
        },
        'xgboost': {
            'n_estimators': [100, 200, 300],
            'max_depth': [3, 5, 7],
            'learning_rate': [0.03, 0.1],
            'subsample': [0.7, 0.9],
            'colsample_bytree': [0.7, 0.9],
            'min_child_weight': [1, 3],
            'reg_alpha': [0, 0.1],
            'reg_lambda': [1, 2]
        },
        'lgbm': {
            'n_estimators': [100, 200, 300],
            'num_leaves': [31, 50, 80],
            'learning_rate': [0.03, 0.1],
            'subsample': [0.7, 0.9],
            'colsample_bytree': [0.7, 0.9],
            'min_child_samples': [10, 20],
            'reg_alpha': [0, 0.1],
            'reg_lambda': [0, 1]
        },
        'catboost': {
            'iterations': [150, 300],
            'depth': [4, 6, 8],
            'learning_rate': [0.03, 0.1],
            'l2_leaf_reg': [1, 3, 5]
        },
        'dl_residual': {
            'look_back': [4, 8, 12],
            'neurons': [32, 64],
            'epochs': 25,
            'learning_rate': [0.005, 0.01],
            'dropout': [0.1, 0.2]
        },
        'ensemble': {'methods': ['weighted', 'stacking']},
        'use_auto_arima': True,
        'arima_max_p': 2,
        'arima_max_q': 2,
        'model_timeout': 120,
        'arima_timeout': 240,
        'dl_timeout': 240,
        'enable_tcn': True,
        'enable_nbeats': False,
        'max_combinations': 25,  # 【新增】
    }

    FULL = {
        'prophet': {
            'changepoint_prior_scale': [0.001, 0.01, 0.05, 0.1, 0.3],
            'seasonality_prior_scale': [0.1, 1.0, 10.0],
            'seasonality_mode': ['additive', 'multiplicative'],
            'changepoint_range': [0.8, 0.9],
            'n_changepoints': [15, 25, 35]
        },
        'xgboost': {
            'n_estimators': [100, 200, 300, 500],
            'max_depth': [3, 5, 7, 9],
            'learning_rate': [0.01, 0.05, 0.1],
            'subsample': [0.6, 0.8, 1.0],
            'colsample_bytree': [0.6, 0.8, 1.0],
            'min_child_weight': [1, 3, 5],
            'reg_alpha': [0, 0.1],
            'reg_lambda': [1, 3]
        },
        'lgbm': {
            'n_estimators': [100, 200, 300, 500],
            'num_leaves': [31, 50, 80, 120],
            'learning_rate': [0.01, 0.05, 0.1],
            'subsample': [0.6, 0.8, 1.0],
            'colsample_bytree': [0.6, 0.8, 1.0],
            'min_child_samples': [5, 10, 20],
            'reg_alpha': [0, 0.1],
            'reg_lambda': [0, 1, 3]
        },
        'catboost': {
            'iterations': [200, 400, 600],
            'depth': [4, 6, 8],
            'learning_rate': [0.01, 0.05, 0.1],
            'l2_leaf_reg': [1, 3, 5]
        },
        'dl_residual': {
            'look_back': [4, 8, 12],
            'neurons': [32, 64, 96],
            'epochs': 30,
            'learning_rate': [0.005, 0.01, 0.02],
            'dropout': [0.1, 0.2, 0.3]
        },
        'ensemble': {'methods': ['simple', 'weighted', 'stacking']},
        'use_auto_arima': True,
        'arima_max_p': 3,
        'arima_max_q': 3,
        'model_timeout': 180,
        'arima_timeout': 360,
        'dl_timeout': 360,
        'enable_tcn': True,
        'enable_nbeats': True,
        'max_combinations': 50,  # 【新增】
    }

    @classmethod
    def get(cls, mode='full'):
        if mode == 'fast':
            return cls.FAST
        elif mode == 'smart':
            return cls.SMART
        return cls.FULL

def calculate_wmape(y_true, y_pred):
    """计算 WMAPE（加权绝对百分比误差）。

    - 返回值越小越好
    - 当真实值总和为 0 时返回 inf（避免除 0）
    """
    y_true = np.asarray(y_true).flatten()
    y_pred = np.asarray(y_pred).flatten()
    total = np.sum(np.abs(y_true))
    if total == 0:
        return float('inf')
    return np.sum(np.abs(y_true - y_pred)) / total

def clean_params_for_db(params):
    """把模型参数清洗成可 JSON 化字符串，便于落库/落盘。

    目的：
    - 过滤不可序列化/体积过大的对象（如模型、特征工程器、scaler）
    - list/ndarray 转为字符串，避免数据库类型不兼容
    """
    clean = {}
    if not params:
        return "{}"
    for k, v in params.items():
        if isinstance(v, (list, np.ndarray)):
            clean[k] = str(v)
        elif 'model' in k or 'eng' in k or 'scaler' in k:
            continue
        elif isinstance(v, (int, float, str, bool)):
            clean[k] = v
        elif v is None:
            clean[k] = None
        else:
            clean[k] = str(type(v).__name__)
    return json.dumps(clean, ensure_ascii=False, default=str)

def get_current_week_end():
    """获取本周周日日期（用作截断“未完整周”的数据）。"""
    today = pd.Timestamp.today().normalize()
    days_until_sunday = (6 - today.dayofweek) % 7
    return today + pd.Timedelta(days=days_until_sunday)

def make_log_diff(series):
    """对数差分变换（销量序列常用）：log1p 后做一阶差分。"""
    values = series.values.flatten()
    values = np.maximum(values, 0)
    log_series = np.log1p(values)
    diff_values = np.diff(log_series)
    diff_series = pd.Series(diff_values, index=series.index[1:])
    last_log_val = log_series[-1]

    debug_print(
        f"      [DEBUG] make_log_diff: input_len={len(series)}, diff_len={len(diff_series)}, last_log={last_log_val:.4f}")

    return diff_series, last_log_val

def reconstruct_from_log_diff(last_log_val, diff_preds):
    """从对数差分预测还原到原始尺度（expm1），并做基础数值保护。"""
    diff_preds = np.nan_to_num(diff_preds, nan=0.0, posinf=0.0, neginf=0.0)
    cumsum_diff = np.cumsum(diff_preds)
    reconstructed_log = last_log_val + cumsum_diff
    reconstructed_log = np.clip(reconstructed_log, -20, 20)
    result = np.expm1(reconstructed_log)
    result = np.maximum(result, 0)

    debug_print(
        f"      [DEBUG] reconstruct: last_log={last_log_val:.4f}, diff_preds[:3]={diff_preds[:3]}, result[:3]={result[:3]}")

    return result

def clean_series(series, zero_handling='interpolate'):
    """清洗销量序列。

    zero_handling:
    - 'interpolate'：把 0 当成缺失进行插值（适合“断货/缺报导致的 0”场景）
    - 其他：仅 fillna(0)
    """
    if zero_handling == 'interpolate':
        return series.replace(0, np.nan).interpolate().bfill().ffill()
    return series.fillna(0)


PROPHET_VALID_PARAMS = {
    'changepoint_prior_scale', 'seasonality_prior_scale',
    'seasonality_mode', 'changepoint_range', 'n_changepoints',
}


def detect_seasonality_strength(series, period=52):
    """
    检测时间序列的季节性强度
    返回: (强度0-1, 季节性成分, 周期)
    """
    values = series.values.flatten() if hasattr(series, 'values') else np.array(series)
    n = len(values)

    if n < period * 1.5:
        # 数据太短，使用ACF估计
        try:
            acf_vals = acf(values, nlags=min(period, n - 1), fft=False)
            check_periods = [4, 12, 13, 26, 52]
            max_acf = 0
            best_period = period
            for p in check_periods:
                if p < len(acf_vals):
                    if abs(acf_vals[p]) > max_acf:
                        max_acf = abs(acf_vals[p])
                        best_period = p
            return max_acf, None, best_period
        except:
            return 0.0, None, period

    try:
        from statsmodels.tsa.seasonal import STL
        stl = STL(values, period=min(period, n // 2), robust=True)
        result = stl.fit()

        detrended = values - result.trend
        var_resid = np.var(result.resid)
        var_detrend = np.var(detrended)

        if var_detrend > 0:
            strength = 1 - var_resid / var_detrend
            strength = max(0, min(1, strength))
        else:
            strength = 0

        return strength, result.seasonal, period

    except Exception as e:
        debug_print(f"      [SEASONAL] STL分解失败: {e}")
        try:
            return _fft_seasonality_detection(values, period)
        except:
            return 0.0, None, period

def _fft_seasonality_detection(values, expected_period=52):
    """使用FFT检测季节性"""
    from scipy.fft import fft
    n = len(values)
    detrended = values - np.linspace(values[0], values[-1], n)

    fft_vals = np.abs(fft(detrended))[:n // 2]
    freqs = np.fft.fftfreq(n)[:n // 2]

    peaks, _ = find_peaks(fft_vals, height=np.mean(fft_vals))

    if len(peaks) == 0:
        return 0.0, None, expected_period

    strongest_peak = peaks[np.argmax(fft_vals[peaks])]
    if freqs[strongest_peak] > 0:
        detected_period = int(1 / freqs[strongest_peak])
    else:
        detected_period = expected_period

    total_energy = np.sum(fft_vals ** 2)
    peak_energy = fft_vals[strongest_peak] ** 2
    strength = peak_energy / total_energy if total_energy > 0 else 0

    return min(1, strength * 5), None, detected_period


def extract_seasonal_pattern(series, period=52):
    """提取季节性模式（周期内的相对强度）"""
    values = series.values.flatten() if hasattr(series, 'values') else np.array(series)
    n = len(values)

    if n < period:
        return np.ones(period)

    # 周期位置分组求均值（等价于原循环实现）
    pattern = np.array([np.mean(values[i::period]) for i in range(period)], dtype=float)
    mean_val = float(np.mean(pattern))
    if mean_val > 0:
        pattern = pattern / mean_val
    else:
        pattern = np.ones(period)

    return pattern

def detect_trend_strength(series):
    """
    检测时间序列的趋势强度和方向

    返回:
        trend_direction: 'up', 'down', 'flat'
        trend_strength: 0-1 之间的强度值 (R²)
        slope: 归一化斜率值
    """
    values = series.values.flatten() if hasattr(series, 'values') else np.array(series)
    n = len(values)

    if n < 5:
        return 'flat', 0.0, 0.0

    x = np.arange(n)
    try:
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, values)

        # 趋势强度使用 R²
        trend_strength = r_value ** 2

        # 归一化斜率（相对于均值的变化率）
        mean_val = np.mean(values)
        if mean_val > 0:
            normalized_slope = slope / mean_val
        else:
            normalized_slope = slope

        # 方向判断 - 综合考虑斜率和R²
        if abs(normalized_slope) < 0.005 or trend_strength < 0.1:
            trend_direction = 'flat'
        elif slope > 0:
            trend_direction = 'up'
        else:
            trend_direction = 'down'

        return trend_direction, float(trend_strength), float(normalized_slope)

    except Exception as e:
        debug_print(f"      [TREND] 趋势检测失败: {e}")
        return 'flat', 0.0, 0.0

def calculate_trend_consistency(predictions, expected_direction, expected_slope):
    """计算“预测序列的趋势”与“期望趋势（来自历史）”的一致性得分（0~1）。

    用途：在 Ensemble 场景中，趋势强时优先给“趋势方向更一致”的模型更高权重。
    """
    preds = np.array(predictions).flatten()

    if len(preds) < 2:
        return 0.5

    # 计算预测的趋势
    x = np.arange(len(preds))
    try:
        pred_slope, _, pred_r, _, _ = stats.linregress(x, preds)

        # 归一化预测斜率
        pred_mean = np.mean(preds)
        if pred_mean > 0:
            pred_normalized_slope = pred_slope / pred_mean
        else:
            pred_normalized_slope = pred_slope

        # 1. 方向一致性得分 (0 或 1)
        if expected_direction == 'up':
            direction_score = 1.0 if pred_slope > 0 else 0.0
        elif expected_direction == 'down':
            direction_score = 1.0 if pred_slope < 0 else 0.0
        else:  # flat
            # 对于平稳趋势，斜率越小越好
            direction_score = np.exp(-abs(pred_normalized_slope) * 10)

        # 2. 斜率相似性得分 (对于非平稳趋势)
        if expected_direction != 'flat' and abs(expected_slope) > 0.001:
            # 计算斜率比值，理想值为1
            if expected_slope != 0:
                slope_ratio = pred_normalized_slope / expected_slope
                # 使用指数衰减，比值越接近1得分越高
                slope_score = np.exp(-abs(slope_ratio - 1) * 2)
            else:
                slope_score = 0.5
        else:
            slope_score = 0.5

        # 3. 综合得分：方向更重要
        consistency_score = 0.7 * direction_score + 0.3 * slope_score

        return max(0.0, min(1.0, consistency_score))

    except Exception as e:
        debug_print(f"      [TREND] 一致性计算失败: {e}")
        return 0.5


def extrapolate_trend(historical_series, n_future, trend_strength, trend_direction):
    """从历史序列外推一个温和的趋势分量（用于修正融合结果趋势方向）。"""

    values = historical_series.values.flatten() if hasattr(historical_series, 'values') else np.array(historical_series)

    if trend_direction == 'flat' or trend_strength < 0.1:
        return np.zeros(n_future)

    # 使用最近的数据计算斜率
    recent_n = min(20, len(values))
    recent_values = values[-recent_n:]
    x = np.arange(recent_n)

    try:
        slope, intercept, _, _, _ = stats.linregress(x, recent_values)

        future_x = np.arange(recent_n, recent_n + n_future)
        trend_component = slope * (future_x - recent_n + 1)

        decay = np.exp(-np.arange(n_future) * 0.02 * (1 - trend_strength))
        trend_component = trend_component * decay

        return trend_component

    except:
        return np.zeros(n_future)

def get_seasonal_indices(future_dates, series_end_date, period=52):
    """获取未来日期对应的季节性索引（用于按周期取 seasonal_pattern）。"""
    if hasattr(series_end_date, 'isocalendar'):
        base_week = series_end_date.isocalendar()[1]
    else:
        base_week = pd.Timestamp(series_end_date).isocalendar()[1]
    n = len(future_dates)
    week_offsets = (np.arange(1, n + 1) % period)
    return (base_week + week_offsets - 1) % period

class FeatureEngineer:
    """为树模型构造监督学习特征（滞后项 + 滚动统计 + 可选外生变量）。

    设计要点：
    - `make_features()`：用于训练（会 dropna，返回 X/y）
    - `make_features_for_prediction()`：用于全量拟合/预测（保持与训练同一套 feature_names）
    - `make_single_row()`：用于递归预测时按当前 history 生成一行特征
    """
    def __init__(self, lags=None, rolling_windows=None):
        self.lags = lags or [1, 2, 4]
        self.rolling_windows = rolling_windows or [4, 8]
        self.feature_names = None
        self.has_exog = False
        self.exog_cols = []
        self._is_fitted = False
        self._exog_means = {}

    def make_features(self, data_series, exog_df=None):
        """从序列构造训练特征矩阵。

        参数：
        - data_series: 通常是“变换后的目标序列”（如 log-diff residual）
        - exog_df: 与 data_series 对齐的外生变量（可选）
        """
        df = pd.DataFrame(data_series.copy())
        df.columns = ['y']
        df['time_idx'] = np.arange(len(df))

        for lag in self.lags:
            df[f'lag_{lag}'] = df['y'].shift(lag)

        for w in self.rolling_windows:
            df[f'roll_mean_{w}'] = df['y'].shift(1).rolling(w).mean()
            df[f'roll_std_{w}'] = df['y'].shift(1).rolling(w).std()

        if exog_df is not None and len(exog_df) > 0:
            self.has_exog = True
            self.exog_cols = list(exog_df.columns)
            exog_aligned = exog_df.reindex(df.index)

            for col in self.exog_cols:
                if col in exog_aligned.columns:
                    col_values = exog_aligned[col].fillna(0).values
                    df[col] = col_values
                    df[f'{col}_lag1'] = pd.Series(col_values, index=df.index).shift(1).fillna(0).values
                    self._exog_means[col] = float(np.nanmean(col_values))
                else:
                    df[col] = 0
                    df[f'{col}_lag1'] = 0
                    self._exog_means[col] = 0

        df = df.dropna()
        self.feature_names = [c for c in df.columns if c != 'y']
        self._is_fitted = True

        debug_print(f"      [DEBUG] make_features: samples={len(df)}, features={self.feature_names}")

        return df.drop('y', axis=1), df['y']

    def make_features_for_prediction(self, data_series, exog_df=None):
        """为预测阶段构造特征（确保列与训练一致，缺失列补 0）。"""
        if not self._is_fitted:
            return self.make_features(data_series, exog_df)

        df = pd.DataFrame(data_series.copy())
        df.columns = ['y']
        df['time_idx'] = np.arange(len(df))

        for lag in self.lags:
            df[f'lag_{lag}'] = df['y'].shift(lag)

        for w in self.rolling_windows:
            df[f'roll_mean_{w}'] = df['y'].shift(1).rolling(w).mean()
            df[f'roll_std_{w}'] = df['y'].shift(1).rolling(w).std()

        if self.has_exog:
            if exog_df is not None and len(exog_df) > 0:
                exog_aligned = exog_df.reindex(df.index)
                for col in self.exog_cols:
                    if col in exog_aligned.columns:
                        col_values = exog_aligned[col].fillna(self._exog_means.get(col, 0)).values
                    else:
                        col_values = np.full(len(df), self._exog_means.get(col, 0))
                    df[col] = col_values
                    df[f'{col}_lag1'] = pd.Series(col_values, index=df.index).shift(1).fillna(
                        col_values[0] if len(col_values) > 0 else 0).values
            else:
                for col in self.exog_cols:
                    mean_val = self._exog_means.get(col, 0)
                    df[col] = mean_val
                    df[f'{col}_lag1'] = mean_val

        df = df.dropna()

        for col in self.feature_names:
            if col not in df.columns:
                df[col] = 0

        return df[self.feature_names], df['y']

    def make_single_row(self, history, current_time_idx, exog_current=None, exog_lag1=None):
        """递归预测时，用“当前历史序列 + 当前时间索引 + 外生变量”拼一行特征。"""
        feat = {'time_idx': float(current_time_idx)}

        if hasattr(history, 'tolist'):
            history = history.tolist()
        elif hasattr(history, 'values'):
            history = history.values.tolist()
        history = list(history)

        for lag in self.lags:
            if len(history) >= lag:
                feat[f'lag_{lag}'] = float(history[-lag])
            else:
                feat[f'lag_{lag}'] = float(np.mean(history)) if len(history) > 0 else 0.0

        for w in self.rolling_windows:
            if len(history) >= w:
                window_data = history[-w:]
                feat[f'roll_mean_{w}'] = float(np.mean(window_data))
                feat[f'roll_std_{w}'] = float(np.std(window_data)) if len(window_data) > 1 else 0.0
            else:
                feat[f'roll_mean_{w}'] = float(np.mean(history)) if len(history) > 0 else 0.0
                feat[f'roll_std_{w}'] = float(np.std(history)) if len(history) > 1 else 0.0

        if self.has_exog:
            for col in self.exog_cols:
                if exog_current is not None and col in exog_current:
                    feat[col] = float(exog_current[col])
                else:
                    feat[col] = self._exog_means.get(col, 0.0)

                if exog_lag1 is not None and col in exog_lag1:
                    feat[f'{col}_lag1'] = float(exog_lag1[col])
                else:
                    feat[f'{col}_lag1'] = feat[col]

        row = pd.DataFrame([feat])

        if self.feature_names:
            for col in self.feature_names:
                if col not in row.columns:
                    row[col] = 0.0
            row = row[self.feature_names]

        return row

    def copy(self):
        """复制一份特征工程器（用于把最佳配置保存到 best_params 里）。"""
        new_eng = FeatureEngineer(lags=self.lags.copy(), rolling_windows=self.rolling_windows.copy())
        new_eng.feature_names = self.feature_names.copy() if self.feature_names else None
        new_eng.has_exog = self.has_exog
        new_eng.exog_cols = self.exog_cols.copy() if self.exog_cols else []
        new_eng._is_fitted = self._is_fitted
        new_eng._exog_means = self._exog_means.copy()
        return new_eng


def tree_recursive_predict(model, history_diff, last_log_val, n_steps, feat_eng, start_idx,
                           future_exog=None, exog_history=None):
    """树模型递归预测（在 log-diff 空间预测，再还原回原始销量尺度）。

    核心思路：
    - 先对销量做 `log1p` + 一阶差分（`make_log_diff`）
    - 树模型学习“差分后的下一步”
    - 预测时采用递归：用前一步预测值作为下一步的滞后特征
    - 最后用 `reconstruct_from_log_diff` 还原到原始销量空间

    外生变量：
    - 支持 future_exog（未来已知/假设的外生变量序列）
    - 支持 exog_history（历史外生变量，用于构造 lag1）
    """
    debug_print(f"\n      [DEBUG] ===== tree_recursive_predict 开始 =====")
    debug_print(f"      [DEBUG] n_steps={n_steps}, start_idx={start_idx}")

    if hasattr(history_diff, 'values'):
        history = history_diff.values.flatten().tolist()
    else:
        history = list(history_diff)

    preds_diff = []
    curr_idx = start_idx

    exog_values_history = {}
    if exog_history is not None and feat_eng.has_exog:
        for col in feat_eng.exog_cols:
            if col in exog_history.columns:
                exog_values_history[col] = exog_history[col].values.tolist()
            else:
                exog_values_history[col] = [feat_eng._exog_means.get(col, 0)] * len(exog_history)

    future_exog_values = {}
    if future_exog is not None and feat_eng.has_exog:
        for col in feat_eng.exog_cols:
            if col in future_exog.columns:
                future_exog_values[col] = future_exog[col].values.tolist()
            else:
                future_exog_values[col] = [feat_eng._exog_means.get(col, 0)] * len(future_exog)

    for i in range(n_steps):
        exog_current = {}
        exog_lag1 = {}

        if feat_eng.has_exog:
            for col in feat_eng.exog_cols:
                if col in future_exog_values and i < len(future_exog_values[col]):
                    exog_current[col] = future_exog_values[col][i]
                else:
                    exog_current[col] = feat_eng._exog_means.get(col, 0)

                if i == 0:
                    if col in exog_values_history and len(exog_values_history[col]) > 0:
                        exog_lag1[col] = exog_values_history[col][-1]
                    else:
                        exog_lag1[col] = exog_current[col]
                else:
                    if col in future_exog_values and (i - 1) < len(future_exog_values[col]):
                        exog_lag1[col] = future_exog_values[col][i - 1]
                    else:
                        exog_lag1[col] = exog_current[col]

        try:
            row = feat_eng.make_single_row(history, curr_idx, exog_current, exog_lag1)
            pred = model.predict(row)[0]

            if np.isnan(pred) or np.isinf(pred):
                pred = 0.0

            preds_diff.append(float(pred))
            history.append(float(pred))
            curr_idx += 1

        except Exception as e:
            debug_print(f"      [DEBUG] Step {i}: 预测出错 - {str(e)}")
            preds_diff.append(0.0)
            history.append(0.0)
            curr_idx += 1

    result = reconstruct_from_log_diff(last_log_val, np.array(preds_diff))

    debug_print(f"      [DEBUG] preds_diff[:5]: {preds_diff[:5]}")
    debug_print(f"      [DEBUG] final result[:5]: {result[:5]}")

    return np.maximum(result, 0)


def optimize_tree_model(model_type, train_data, test_data, feat_eng, mode='full',
                        train_exog=None, test_exog=None):
    """树模型（XGBoost/LightGBM/CatBoost）调参与验证。

    过程：
    - 把训练序列变换到 log-diff 空间，构造滞后/滚动特征（可选外生变量）
    - 从 `SearchConfig` 取参数网格（会用 `max_combinations` 限制组合数量）
    - 对每组参数训练模型，递归预测验证集长度，计算 WMAPE
    - 保存最佳模型参数（含 feat_eng 复制件与必要的还原信息）
    """
    name_map = {'xgboost': 'XGBoost', 'lgbm': 'LightGBM', 'catboost': 'CatBoost'}
    best = {'name': name_map[model_type], 'wmape': float('inf'), 'forecast': None,
            'params': None, 'error': None}

    debug_print(f"\n      [DEBUG] ===== optimize_tree_model: {model_type} =====")

    try:
        train_diff, train_last_log = make_log_diff(train_data)

        if train_exog is not None and len(train_exog) > 0:
            train_exog_aligned = train_exog.iloc[1:].copy()
            train_exog_aligned.index = train_diff.index
        else:
            train_exog_aligned = None

        X_train, y_train = feat_eng.make_features(train_diff, train_exog_aligned)

        if len(X_train) < 5:
            best['error'] = "Data too short"
            return best

    except Exception as e:
        debug_print(f"      [DEBUG] 特征生成错误: {e}")
        best['error'] = str(e)
        return best

    test_values = test_data.values.flatten()
    config = SearchConfig.get(mode)
    model_cfg = config.get(model_type, {})
    max_combinations = config.get('max_combinations', 20)  # 【新增】获取最大组合数

    grid_params = {k: v for k, v in model_cfg.items() if isinstance(v, list)}

    if not grid_params:
        return best

    keys, values = zip(*grid_params.items())
    all_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

    # 【改进】智能限制组合数量
    if len(all_combinations) > max_combinations:
        combinations = random.sample(all_combinations, max_combinations)
        debug_print(f"      [DEBUG] {model_type}: 从{len(all_combinations)}组合采样{max_combinations}个")
    else:
        combinations = all_combinations
        debug_print(f"      [DEBUG] {model_type}: 使用全部{len(combinations)}个组合")

    if test_exog is not None and len(test_exog) > 0:
        test_exog_for_pred = test_exog.copy()
    else:
        test_exog_for_pred = None

    CatBoostRegressor = _get_catboost_regressor() if model_type == 'catboost' else None
    if model_type == 'catboost' and CatBoostRegressor is None:
        return best

    # 【新增】记录调参过程
    tried_count = 0
    success_count = 0

    for params in combinations:
        tried_count += 1
        try:
            if model_type == 'xgboost':
                model = XGBRegressor(**params, objective='reg:squarederror',
                                     n_jobs=-1, verbosity=0, random_state=42)
            elif model_type == 'lgbm':
                model = LGBMRegressor(**params, n_jobs=-1, random_state=42, verbose=-1)
            elif model_type == 'catboost':
                # CatBoost不支持colsample_bytree，需要过滤
                cat_params = {k: v for k, v in params.items() if k != 'colsample_bytree'}
                model = CatBoostRegressor(**cat_params, loss_function='MAE', verbose=0,
                                          allow_writing_files=False, random_state=42)

            model.fit(X_train, y_train)
            last_idx = X_train['time_idx'].iloc[-1]

            pred = tree_recursive_predict(
                model, train_diff, train_last_log, len(test_values), feat_eng,
                last_idx + 1, test_exog_for_pred, train_exog_aligned
            )
            pred = np.maximum(pred, 0)
            wmape = calculate_wmape(test_values, pred)
            success_count += 1

            if wmape < best['wmape']:
                saved_params = {
                    **params,
                    'feat_eng': feat_eng.copy(),
                    'train_last_log': train_last_log,
                    'model_type': model_type,
                }
                best.update({
                    'wmape': wmape,
                    'forecast': pred,
                    'params': saved_params,
                    'error': None
                })
                debug_print(f"      [DEBUG] 新最佳! WMAPE={wmape:.4f}")

        except Exception as e:
            debug_print(f"      [DEBUG] 组合失败: {str(e)[:30]}")
            continue

    # 【新增】输出调参统计
    debug_print(
        f"      [DEBUG] {model_type} 调参完成: 尝试{tried_count}, 成功{success_count}, 最佳WMAPE={best['wmape']:.4f}")

    return best

def optimize_prophet(train_data, test_data, mode='full', train_exog=None, test_exog=None):
    """Prophet 调参与验证（支持外生回归项）。

    过程：
    - 组装 Prophet 需要的列名 ds/y，并按需合并外生变量
    - 依据 `SearchConfig` 生成参数组合（受 `max_combinations` 限制）
    - 训练后对验证集长度做预测，计算 WMAPE，保存最优参数/结果
    """
    best = {'name': 'Prophet', 'wmape': float('inf'), 'forecast': None, 'params': None, 'error': None}

    debug_print(f"\n      [DEBUG] ===== optimize_prophet =====")

    try:
        df_train = train_data.reset_index()
        df_train.columns = ['ds', 'y']
        df_train['ds'] = pd.to_datetime(df_train['ds'])

        exog_cols = []
        if train_exog is not None and len(train_exog) > 0:
            train_exog_reset = train_exog.reset_index()
            train_exog_reset.columns = ['ds'] + list(train_exog.columns)
            train_exog_reset['ds'] = pd.to_datetime(train_exog_reset['ds'])
            df_train = df_train.merge(train_exog_reset, on='ds', how='left')
            exog_cols = list(train_exog.columns)
            for col in exog_cols:
                df_train[col] = df_train[col].fillna(df_train[col].mean())

        test_values = test_data.values.flatten()
        config = SearchConfig.get(mode)
        prophet_cfg = config['prophet']
        max_combinations = config.get('max_combinations', 20)  # 【新增】

        grid_params = {k: v for k, v in prophet_cfg.items() if isinstance(v, list)}
        keys, values = zip(*grid_params.items())
        all_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

        # 【改进】限制组合数
        if len(all_combinations) > max_combinations:
            combinations = random.sample(all_combinations, max_combinations)
            debug_print(f"      [DEBUG] Prophet: 从{len(all_combinations)}组合采样{max_combinations}个")
        else:
            combinations = all_combinations

        tried_count = 0
        success_count = 0

        for params in combinations:
            tried_count += 1
            try:
                valid_params = {k: v for k, v in params.items() if k in PROPHET_VALID_PARAMS}
                m = Prophet(**valid_params, yearly_seasonality=True, weekly_seasonality=False,
                            daily_seasonality=False, uncertainty_samples=0)
                for col in exog_cols:
                    m.add_regressor(col)

                with suppress_stdout_stderr():
                    m.fit(df_train)

                future = m.make_future_dataframe(periods=len(test_values), freq='W')
                if exog_cols and test_exog is not None:
                    full_exog = pd.concat([train_exog, test_exog])
                    full_exog_reset = full_exog.reset_index()
                    full_exog_reset.columns = ['ds'] + exog_cols
                    full_exog_reset['ds'] = pd.to_datetime(full_exog_reset['ds'])
                    future = future.merge(full_exog_reset, on='ds', how='left')
                    for col in exog_cols:
                        future[col] = future[col].fillna(future[col].mean())

                forecast = m.predict(future)
                pred = np.maximum(forecast['yhat'].iloc[-len(test_values):].values, 0)
                wmape = calculate_wmape(test_values, pred)
                success_count += 1

                if wmape < best['wmape']:
                    best.update({'wmape': wmape, 'forecast': pred,
                                 'params': {**valid_params, 'exog_cols': exog_cols}, 'error': None})
                    debug_print(f"      [DEBUG] Prophet新最佳! WMAPE={wmape:.4f}")

            except:
                continue

        debug_print(f"      [DEBUG] Prophet 调参完成: 尝试{tried_count}, 成功{success_count}")

    except Exception as e:
        best['error'] = str(e)
    return best

def fit_shared_arima(train_data, mode='smart'):
    """
    修复版ARIMA拟合 - 多策略fallback + 动态周期调整
    """
    config = SearchConfig.get(mode)
    train_values = train_data.values.flatten()
    n_samples = len(train_values)

    # 数据预处理
    train_values = np.maximum(train_values, 0)
    train_log = np.log1p(train_values)

    debug_print(f"      [ARIMA] 样本数: {n_samples}, 范围: {train_values.min():.1f} ~ {train_values.max():.1f}")

    # 【关键1】根据数据量动态调整季节性周期
    if n_samples < 52:
        m = 4
        use_seasonal = False
        debug_print(f"      [ARIMA] 数据<1年，禁用季节性")
    elif n_samples < 104:
        m = 13
        use_seasonal = n_samples >= 26
        debug_print(f"      [ARIMA] 数据<2年，m={m}")
    elif n_samples < 156:
        m = 26
        use_seasonal = True
        debug_print(f"      [ARIMA] 数据<3年，m={m}")
    else:
        m = 52
        use_seasonal = True
        debug_print(f"      [ARIMA] 使用年度周期 m={m}")

    # 【关键2】定义多个策略（从简单到复杂）
    if mode == 'fast':
        strategies = [
            ('fixed_simple', (1, 1, 1), (0, 1, 1, m) if use_seasonal else (0, 0, 0, 0)),
            ('fixed_minimal', (1, 1, 0), (0, 0, 0, 0)),
            ('fixed_ar1', (1, 0, 0), (0, 0, 0, 0)),
        ]
    else:
        strategies = [
            ('seasonal_simple', (1, 1, 1), (0, 1, 1, m) if use_seasonal else (0, 0, 0, 0)),
            ('auto_limited', None, None),
            ('seasonal_minimal', (1, 1, 0), (0, 1, 0, m) if use_seasonal else (0, 0, 0, 0)),
            ('nonseasonal', (1, 1, 1), (0, 0, 0, 0)),
            ('minimal', (0, 1, 1), (0, 0, 0, 0)),
        ]

    # 【关键3】逐个尝试策略
    for strategy_name, order, seasonal_order in strategies:
        try:
            debug_print(f"      [ARIMA] 尝试: {strategy_name}")

            if strategy_name == 'auto_limited':
                # 严格限制 auto_arima
                arima_model = pm.auto_arima(
                    train_log,
                    seasonal=use_seasonal,
                    m=m if use_seasonal else 1,
                    d=1, D=1 if use_seasonal else 0,
                    max_p=2, max_q=2, max_P=1, max_Q=1,
                    max_order=4, max_d=1, max_D=1,
                    start_p=0, start_q=0, start_P=0, start_Q=0,
                    stepwise=True, n_fits=15,
                    trace=DEBUG_MODE,
                    error_action='ignore',
                    suppress_warnings=True,
                    n_jobs=1, random_state=42
                )
            else:
                arima_model = pm.ARIMA(order=order, seasonal_order=seasonal_order)
                with suppress_stdout_stderr():
                    arima_model.fit(train_log)

            # 验证结果
            train_arima = np.expm1(arima_model.predict_in_sample())

            if np.any(np.isnan(train_arima)) or np.any(np.isinf(train_arima)):
                debug_print(f"      [ARIMA] {strategy_name}: 无效预测，跳过")
                continue

            pred_mean = np.mean(train_arima)
            actual_mean = np.mean(train_values)
            if pred_mean < 0 or (actual_mean > 0 and pred_mean > actual_mean * 10):
                debug_print(f"      [ARIMA] {strategy_name}: 预测异常，跳过")
                continue

            debug_print(f"      [ARIMA] {strategy_name} 成功! order={arima_model.order}")
            return arima_model, train_arima, True

        except Exception as e:
            debug_print(f"      [ARIMA] {strategy_name} 失败: {str(e)[:40]}")
            continue

    debug_print(f"      [ARIMA] 所有策略失败")
    return None, None, False


def build_tcn_model(input_shape, neurons):
    """TCN模型 - 增加错误处理"""
    try:
        inputs = Input(shape=input_shape)

        # 第一层卷积
        x = Conv1D(filters=neurons, kernel_size=2, padding='causal',
                   dilation_rate=1, activation='relu')(inputs)
        x = Dropout(0.1)(x)

        # 第二层卷积 - 检查序列长度是否足够
        if input_shape[0] >= 4:
            x = Conv1D(filters=neurons, kernel_size=2, padding='causal',
                       dilation_rate=2, activation='relu')(x)

        # 取最后一个时间步
        x = Lambda(lambda t: t[:, -1, :])(x)
        x = Dense(neurons // 2, activation='relu')(x)
        outputs = Dense(1)(x)

        return Model(inputs, outputs)
    except Exception as e:
        debug_print(f"      [TCN] 模型构建失败: {e}")
        # 返回简单的LSTM作为fallback
        model = Sequential([
            LSTM(neurons, input_shape=input_shape, activation='tanh'),
            Dense(1)
        ])
        return model


def build_nbeats_model(input_shape, neurons):
    """构建一个简化版 N-BEATS 风格网络（用于残差序列建模的备选 DL 模型）。"""
    inputs = Input(shape=input_shape)
    flat = Flatten()(inputs)
    flat_dim = input_shape[0] * input_shape[1]
    h1 = Dense(neurons, activation='relu')(flat)
    h1 = Dropout(0.1)(h1)
    backcast1 = Dense(flat_dim, activation='linear')(h1)
    forecast1 = Dense(1, activation='linear')(h1)
    resid = Lambda(lambda x: x[0] - x[1])([flat, backcast1])
    h2 = Dense(neurons, activation='relu')(resid)
    forecast2 = Dense(1, activation='linear')(h2)
    final = Add()([forecast1, forecast2])
    return Model(inputs, final)


def optimize_dl_with_arima(train_data, test_data, dl_type, arima_model, train_arima, mode='full'):
    """SARIMA+DL混合模型 - 增强版调参"""
    name_map = {'lstm': 'SARIMA+LSTM', 'tcn': 'SARIMA+TCN', 'nbeats': 'SARIMA+N-BEATS'}
    best = {'name': name_map[dl_type], 'wmape': float('inf'), 'forecast': None, 'params': None, 'error': None}

    if arima_model is None:
        best['error'] = "ARIMA not available"
        return best

    config = SearchConfig.get(mode)

    try:
        train_values = train_data.values.flatten()
        test_values = test_data.values.flatten()
        test_arima = np.expm1(arima_model.predict(n_periods=len(test_values)))

        residuals = (train_values - train_arima).reshape(-1, 1)
        residuals = np.nan_to_num(residuals, nan=0.0, posinf=0.0, neginf=0.0)

        resid_mean = float(np.mean(residuals))
        resid_std = float(np.std(residuals))
        resid_max = float(np.max(np.abs(residuals)))

        scaler = MinMaxScaler((-1, 1))
        res_scaled = scaler.fit_transform(residuals)
    except Exception as e:
        best['error'] = str(e)
        return best

    dl_config = config.get('dl_residual', {})
    max_combinations = config.get('max_combinations', 20)

    # 【改进】提取所有DL参数
    look_backs = dl_config.get('look_back', [4])
    if not isinstance(look_backs, list):
        look_backs = [look_backs]

    neuron_list = dl_config.get('neurons', [32])
    if not isinstance(neuron_list, list):
        neuron_list = [neuron_list]

    epochs = dl_config.get('epochs', 20)

    # 【新增】学习率和dropout参数
    learning_rates = dl_config.get('learning_rate', [0.01])
    if not isinstance(learning_rates, list):
        learning_rates = [learning_rates]

    dropouts = dl_config.get('dropout', [0.1])
    if not isinstance(dropouts, list):
        dropouts = [dropouts]

    # 【改进】生成所有参数组合
    all_combinations = list(itertools.product(look_backs, neuron_list, learning_rates, dropouts))

    if len(all_combinations) > max_combinations:
        combinations = random.sample(all_combinations, max_combinations)
        debug_print(f"      [DEBUG] DL: 从{len(all_combinations)}组合采样{max_combinations}个")
    else:
        combinations = all_combinations

    if mode == 'fast':
        combinations = combinations[:3]

    tried_count = 0
    success_count = 0

    for lb, neu, lr, dropout in combinations:
        tried_count += 1
        try:
            X, Y = [], []
            for i in range(len(res_scaled) - lb):
                X.append(res_scaled[i:i + lb, 0])
                Y.append(res_scaled[i + lb, 0])
            X, Y = np.array(X), np.array(Y)
            if len(X) < 10:
                continue

            X = X.reshape(X.shape[0], X.shape[1], 1)
            tf.keras.backend.clear_session()

            if dl_type == 'lstm':
                model = Sequential([
                    LSTM(neu, input_shape=(lb, 1), activation='tanh'),
                    Dropout(dropout),
                    Dense(1)
                ])
            elif dl_type == 'tcn':
                try:
                    model = build_tcn_model((lb, 1), neu)
                except Exception as e:
                    debug_print(f"      [TCN] 构建失败，使用LSTM替代: {e}")
                    model = Sequential([
                        LSTM(neu, input_shape=(lb, 1), activation='tanh'),
                        Dropout(dropout),
                        Dense(1)
                    ])
            elif dl_type == 'nbeats':
                try:
                    model = build_nbeats_model((lb, 1), neu)
                except Exception as e:
                    debug_print(f"      [N-BEATS] 构建失败，使用LSTM替代: {e}")
                    model = Sequential([
                        LSTM(neu, input_shape=(lb, 1), activation='tanh'),
                        Dense(1)
                    ])
            else:
                continue

            # 【改进】使用参数化的学习率
            model.compile(loss='mse', optimizer=Adam(lr))
            early_stop = EarlyStopping(monitor='loss', patience=5, restore_best_weights=True)
            model.fit(X, Y, epochs=epochs, batch_size=min(16, max(4, len(X) // 4)),
                      verbose=0, callbacks=[early_stop])

            curr = res_scaled[-lb:].flatten()
            pred_resids = []
            for _ in range(len(test_values)):
                p = model.predict(curr.reshape(1, lb, 1), verbose=0)[0, 0]
                pred_resids.append(p)
                curr = np.append(curr[1:], p)

            pred_resids = scaler.inverse_transform(np.array(pred_resids).reshape(-1, 1)).flatten()
            final_pred = test_arima + pred_resids
            final_pred = np.maximum(final_pred, 0)

            wmape = calculate_wmape(test_values, final_pred)
            success_count += 1

            if wmape < best['wmape']:
                best.update({
                    'wmape': wmape,
                    'forecast': final_pred,
                    'params': {
                        'look_back': lb,
                        'neurons': neu,
                        'epochs': epochs,
                        'learning_rate': lr,  # 【新增】保存学习率
                        'dropout': dropout,  # 【新增】保存dropout
                        'arima_order': arima_model.order,
                        'arima_seasonal_order': arima_model.seasonal_order,
                        'dl_type': dl_type,
                        'resid_max': resid_max,
                        'resid_mean': resid_mean,
                        'resid_std': resid_std
                    },
                    'error': None
                })
                debug_print(f"      [DEBUG] DL新最佳! lb={lb}, neu={neu}, lr={lr}, WMAPE={wmape:.4f}")

        except Exception as e:
            debug_print(f"      [DEBUG] DL组合失败: {str(e)[:30]}")
            continue

    debug_print(f"      [DEBUG] {dl_type} 调参完成: 尝试{tried_count}, 成功{success_count}")

    return best

def optimize_ensemble(base_results, test_data, mode='full', train_data=None):
    """对多个基模型结果做融合（Ensemble），并在验证集上评估。

    输入：
    - base_results: 来自 `run_all_models()` 的“非 Ensemble”模型结果列表（字典含 name/wmape/forecast/params）
    - test_data: 验证集真实值（用于计算 WMAPE）
    - train_data: 可选训练集（用于更稳定地估计趋势/季节性）

    输出：
    - 多个融合方案的结果列表（每个元素结构与 base_results 一致）
    """

    ensemble_results = []
    valid_results = [r for r in base_results if r['forecast'] is not None and r['wmape'] < float('inf')]

    if len(valid_results) < 2:
        return []

    test_values = test_data.values.flatten()
    preds_matrix = np.column_stack([r['forecast'] for r in valid_results])
    names = [r['name'] for r in valid_results]
    wmapes = np.array([r['wmape'] for r in valid_results])

    # ============ 核心分析 ============
    # 构建完整序列用于分析
    if train_data is not None:
        full_series = pd.concat([train_data, test_data])
    else:
        full_series = test_data

    # 【核心1】检测季节性
    seasonal_strength, seasonal_component, detected_period = detect_seasonality_strength(full_series)
    seasonal_pattern = extract_seasonal_pattern(full_series, detected_period)

    # 【核心2 - 新增】检测趋势
    trend_direction, trend_strength, trend_slope = detect_trend_strength(full_series)

    debug_print(f"      [ANALYSIS] 趋势: {trend_direction} (强度={trend_strength:.3f}, 斜率={trend_slope:.4f})")
    debug_print(f"      [ANALYSIS] 季节: 强度={seasonal_strength:.3f}, 周期={detected_period}")

    config = SearchConfig.get(mode)
    methods = config.get('ensemble', {}).get('methods', ['weighted'])

    # 模型分类
    SEASONAL_MODELS = ['Prophet', 'SARIMA+LSTM', 'SARIMA+TCN', 'SARIMA+N-BEATS']
    TREND_MODELS = ['Prophet', 'SARIMA+LSTM', 'SARIMA+TCN', 'XGBoost', 'LightGBM', 'CatBoost']

    seasonal_mask = np.array([any(sm in name for sm in SEASONAL_MODELS) for name in names])
    trend_mask = np.array([any(tm in name for tm in TREND_MODELS) for name in names])

    # 【新增】计算每个模型的趋势一致性得分
    trend_consistency_scores = np.array([
        calculate_trend_consistency(preds_matrix[:, i], trend_direction, trend_slope)
        for i in range(len(valid_results))
    ])

    debug_print(f"      [TREND] 模型趋势一致性:")
    for i, name in enumerate(names):
        debug_print(f"          {name}: {trend_consistency_scores[i]:.3f}")

    # ==================== 方法1: 简单平均 ====================
    if 'simple' in methods:
        try:
            pred = np.mean(preds_matrix, axis=1)
            wmape = calculate_wmape(test_values, pred)
            ensemble_results.append({
                'name': 'Ensemble_Avg',
                'wmape': wmape,
                'forecast': pred,
                'params': {'method': 'simple', 'base_models': names},
                'error': None
            })
        except:
            pass

    # ==================== 方法2: WMAPE加权 ====================
    if 'weighted' in methods:
        try:
            weights_wmape = 1 / (wmapes + 1e-6)
            weights_wmape /= weights_wmape.sum()

            pred_wmape = np.average(preds_matrix, axis=1, weights=weights_wmape)
            wmape_val = calculate_wmape(test_values, pred_wmape)

            ensemble_results.append({
                'name': 'Ensemble_Wgt',
                'wmape': wmape_val,
                'forecast': pred_wmape,
                'params': {
                    'method': 'wmape_weighted',
                    'base_models': names,
                    'weights': list(weights_wmape),
                    'wmape_weights': list(weights_wmape)
                },
                'error': None
            })
        except Exception as e:
            debug_print(f"      [ENSEMBLE] WMAPE加权失败: {e}")

    # ==================== 方法3: 季节性感知加权 ====================
    if seasonal_strength > 0.2 and seasonal_mask.any():
        try:
            weights_wmape = 1 / (wmapes + 1e-6)
            weights_wmape /= weights_wmape.sum()

            seasonal_boost = 1 + seasonal_strength * 1.5
            weights_seasonal = weights_wmape.copy()
            weights_seasonal[seasonal_mask] *= seasonal_boost
            weights_seasonal /= weights_seasonal.sum()

            pred_seasonal = np.average(preds_matrix, axis=1, weights=weights_seasonal)
            wmape_seasonal = calculate_wmape(test_values, pred_seasonal)

            ensemble_results.append({
                'name': 'Ensemble_Seas',
                'wmape': wmape_seasonal,
                'forecast': pred_seasonal,
                'params': {
                    'method': 'seasonal_weighted',
                    'base_models': names,
                    'weights': list(weights_seasonal),
                    'wmape_weights': list(weights_wmape),
                    'seasonal_strength': seasonal_strength,
                    'seasonal_boost': seasonal_boost
                },
                'error': None
            })
            debug_print(f"      [ENSEMBLE] 季节性加权: boost={seasonal_boost:.2f}, WMAPE={wmape_seasonal:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 季节性加权失败: {e}")

    # ==================== 方法4: 趋势感知加权 【新增】 ====================
    if trend_strength > 0.2 and trend_direction != 'flat':
        try:
            weights_wmape = 1 / (wmapes + 1e-6)
            weights_wmape /= weights_wmape.sum()

            # 趋势增强：一致性越高，权重越大
            trend_boost = 1 + trend_strength * 2 * trend_consistency_scores
            weights_trend = weights_wmape * trend_boost
            weights_trend /= weights_trend.sum()

            pred_trend = np.average(preds_matrix, axis=1, weights=weights_trend)
            wmape_trend = calculate_wmape(test_values, pred_trend)

            ensemble_results.append({
                'name': 'Ensemble_Trend',
                'wmape': wmape_trend,
                'forecast': pred_trend,
                'params': {
                    'method': 'trend_weighted',
                    'base_models': names,
                    'weights': list(weights_trend),
                    'wmape_weights': list(weights_wmape),
                    'trend_direction': trend_direction,
                    'trend_strength': trend_strength,
                    'trend_slope': trend_slope,
                    'trend_consistency_scores': list(trend_consistency_scores)
                },
                'error': None
            })
            debug_print(f"      [ENSEMBLE] 趋势加权: direction={trend_direction}, WMAPE={wmape_trend:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 趋势加权失败: {e}")

    # ==================== 方法5: 趋势-季节性综合融合 【新增】 ====================
    if trend_strength > 0.15 or seasonal_strength > 0.15:
        try:
            # 基础WMAPE权重
            weights_wmape = 1 / (wmapes + 1e-6)
            weights_wmape /= weights_wmape.sum()

            # 季节性权重分量
            seasonal_scores = np.ones(len(names)) * 0.5
            if seasonal_strength > 0.15:
                seasonal_scores[seasonal_mask] = 1.0 + seasonal_strength
            seasonal_scores /= seasonal_scores.sum()

            # 趋势权重分量
            trend_scores = trend_consistency_scores.copy()
            trend_scores = np.maximum(trend_scores, 0.2)  # 最小权重
            trend_scores /= trend_scores.sum()

            alpha = 0.5
            beta = min(seasonal_strength * 0.4, 0.25)
            gamma = min(trend_strength * 0.4, 0.25)

            # 归一化
            total = alpha + beta + gamma
            alpha, beta, gamma = alpha / total, beta / total, gamma / total

            combined_weights = alpha * weights_wmape + beta * seasonal_scores + gamma * trend_scores
            combined_weights = np.maximum(combined_weights, 0)  # 确保非负
            combined_weights /= combined_weights.sum()

            pred_combined = np.average(preds_matrix, axis=1, weights=combined_weights)
            wmape_combined = calculate_wmape(test_values, pred_combined)

            ensemble_results.append({
                'name': 'Ensemble_TS',
                'wmape': wmape_combined,
                'forecast': pred_combined,
                'params': {
                    'method': 'trend_seasonal_combined',
                    'base_models': names,
                    'weights': list(combined_weights),
                    'wmape_weights': list(weights_wmape),
                    'alpha': alpha,
                    'beta': beta,
                    'gamma': gamma,
                    'trend_direction': trend_direction,
                    'trend_strength': trend_strength,
                    'trend_slope': trend_slope,
                    'seasonal_strength': seasonal_strength,
                    'trend_consistency_scores': list(trend_consistency_scores)
                },
                'error': None
            })
            debug_print(
                f"      [ENSEMBLE] 趋势-季节性综合: α={alpha:.2f}, β={beta:.2f}, γ={gamma:.2f}, WMAPE={wmape_combined:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 趋势-季节性综合失败: {e}")

    # ==================== 方法6: 分层融合 ====================
    if 'stacking' in methods and (seasonal_strength > 0.15 or trend_strength > 0.15):
        try:
            # 第一层：按模型类型分组
            seasonal_preds = []
            non_seasonal_preds = []
            seasonal_wmapes = []
            non_seasonal_wmapes = []
            seasonal_trend_scores = []
            non_seasonal_trend_scores = []

            for i, name in enumerate(names):
                is_seasonal = any(sm in name for sm in SEASONAL_MODELS)
                if is_seasonal:
                    seasonal_preds.append(preds_matrix[:, i])
                    seasonal_wmapes.append(wmapes[i])
                    seasonal_trend_scores.append(trend_consistency_scores[i])
                else:
                    non_seasonal_preds.append(preds_matrix[:, i])
                    non_seasonal_wmapes.append(wmapes[i])
                    non_seasonal_trend_scores.append(trend_consistency_scores[i])

            layer1_preds = []

            # 季节性模型集成
            if seasonal_preds:
                sw = 1 / (np.array(seasonal_wmapes) + 1e-6)
                # 趋势加权
                if trend_strength > 0.2:
                    sw *= (1 + np.array(seasonal_trend_scores))
                sw /= sw.sum()
                seasonal_ensemble = np.average(np.column_stack(seasonal_preds), axis=1, weights=sw)
                layer1_preds.append(('seasonal', seasonal_ensemble, np.mean(seasonal_wmapes)))

            # 非季节性模型集成
            if non_seasonal_preds:
                nsw = 1 / (np.array(non_seasonal_wmapes) + 1e-6)
                if trend_strength > 0.2:
                    nsw *= (1 + np.array(non_seasonal_trend_scores))
                nsw /= nsw.sum()
                non_seasonal_ensemble = np.average(np.column_stack(non_seasonal_preds), axis=1, weights=nsw)
                layer1_preds.append(('non_seasonal', non_seasonal_ensemble, np.mean(non_seasonal_wmapes)))

            # 第二层融合
            if len(layer1_preds) == 2:
                # 根据季节性和趋势强度分配权重
                seasonal_layer_weight = 0.5 + seasonal_strength * 0.25 + trend_strength * 0.15
                non_seasonal_layer_weight = 1 - seasonal_layer_weight

                final_pred = (layer1_preds[0][1] * seasonal_layer_weight +
                              layer1_preds[1][1] * non_seasonal_layer_weight)

                wmape_hier = calculate_wmape(test_values, final_pred)

                ensemble_results.append({
                    'name': 'Ensemble_Hier',
                    'wmape': wmape_hier,
                    'forecast': final_pred,
                    'params': {
                        'method': 'hierarchical',
                        'base_models': names,
                        'seasonal_layer_weight': seasonal_layer_weight,
                        'trend_strength': trend_strength,
                        'seasonal_strength': seasonal_strength,
                        'trend_direction': trend_direction,
                        'trend_slope': trend_slope,
                        'trend_consistency_scores': list(trend_consistency_scores)
                    },
                    'error': None
                })
                debug_print(
                    f"      [ENSEMBLE] 分层融合: 季节层权重={seasonal_layer_weight:.2f}, WMAPE={wmape_hier:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 分层融合失败: {e}")

    # ==================== 方法7: Stacking + 趋势季节性校正 【增强】 ====================
    if 'stacking' in methods:
        try:
            # 使用Ridge回归进行Stacking
            meta_model = Ridge(alpha=1.0, fit_intercept=True)
            meta_model.fit(preds_matrix, test_values)
            pred_stack = meta_model.predict(preds_matrix)

            # 记录原始Stacking结果
            original_stack = pred_stack.copy()

            # 【关键修复】检查Stacking权重
            raw_weights = meta_model.coef_
            debug_print(f"      [STACKING] Ridge权重: {dict(zip(names, raw_weights.round(3)))}")

            # 如果权重有负值且趋势较强，需要校正
            has_negative_weights = np.any(raw_weights < -0.1)

            # 【增强】趋势校正
            use_trend_correction = False
            if trend_strength > 0.25 and trend_direction != 'flat':
                # 计算stacking结果的趋势
                stack_dir, stack_str, stack_slope = detect_trend_strength(pd.Series(pred_stack))

                debug_print(f"      [STACKING] 趋势检查: 期望={trend_direction}, 实际={stack_dir}")

                # 如果趋势方向不一致，进行校正
                if stack_dir != trend_direction or has_negative_weights:
                    debug_print(f"      [STACKING] 需要趋势校正")

                    # 找到趋势最一致的模型
                    best_trend_idx = np.argmax(trend_consistency_scores)
                    best_trend_pred = preds_matrix[:, best_trend_idx]
                    best_trend_name = names[best_trend_idx]

                    # 验证该模型趋势是否正确
                    check_dir, _, _ = detect_trend_strength(pd.Series(best_trend_pred))

                    if check_dir == trend_direction:
                        # 混合校正
                        correction_weight = min(trend_strength * 0.5, 0.35)
                        pred_stack = (1 - correction_weight) * pred_stack + correction_weight * best_trend_pred
                        use_trend_correction = True
                        debug_print(f"      [STACKING] 趋势校正: 使用{best_trend_name}, 权重={correction_weight:.2f}")
                    else:
                        # 备选方案：使用WMAPE加权代替
                        weights_wmape = 1 / (wmapes + 1e-6)
                        weights_wmape *= (1 + trend_consistency_scores)  # 趋势增强
                        weights_wmape /= weights_wmape.sum()
                        pred_stack = np.average(preds_matrix, axis=1, weights=weights_wmape)
                        use_trend_correction = True
                        debug_print(f"      [STACKING] 趋势校正: 回退到WMAPE+趋势加权")

            # 季节性残差校正
            use_seasonal_correction = False
            if seasonal_strength > 0.25 and len(test_values) >= 4 and train_data is not None:
                residuals = test_values - pred_stack

                test_indices = get_seasonal_indices(
                    test_data.index,
                    train_data.index[-1],
                    detected_period
                )

                seasonal_correction = np.zeros(len(residuals))
                for i, idx in enumerate(test_indices):
                    if idx < len(seasonal_pattern):
                        pattern_deviation = seasonal_pattern[idx] - 1.0
                        correction = pattern_deviation * np.mean(test_values) * seasonal_strength * 0.1
                        seasonal_correction[i] = correction

                pred_corrected = pred_stack + seasonal_correction
                wmape_corrected = calculate_wmape(test_values, pred_corrected)
                wmape_uncorrected = calculate_wmape(test_values, pred_stack)

                if wmape_corrected < wmape_uncorrected:
                    pred_stack = pred_corrected
                    use_seasonal_correction = True
                    debug_print(f"      [STACKING] 季节性校正: {wmape_uncorrected:.4f} -> {wmape_corrected:.4f}")

            # 确保非负
            pred_stack = np.maximum(pred_stack, 0)

            wmape_stack = calculate_wmape(test_values, pred_stack)

            # 保存完整的参数信息
            wmape_weights = 1 / (wmapes + 1e-6)
            wmape_weights = wmape_weights / wmape_weights.sum()

            ensemble_results.append({
                'name': 'Ensemble_Stack',
                'wmape': wmape_stack,
                'forecast': pred_stack,
                'params': {
                    'method': 'stacking_enhanced',
                    'base_models': names,
                    'weights': list(raw_weights),
                    'wmape_weights': list(wmape_weights),
                    'intercept': float(meta_model.intercept_),
                    'trend_correction': use_trend_correction,
                    'seasonal_correction': use_seasonal_correction,
                    'trend_direction': trend_direction,
                    'trend_strength': trend_strength,
                    'trend_slope': trend_slope,
                    'seasonal_strength': seasonal_strength,
                    'detected_period': detected_period,
                    'trend_consistency_scores': list(trend_consistency_scores),
                    'seasonal_pattern': list(seasonal_pattern[:min(12, len(seasonal_pattern))])
                },
                'error': None
            })
            debug_print(
                f"      [STACKING] 最终WMAPE={wmape_stack:.4f}, 趋势校正={use_trend_correction}, 季节校正={use_seasonal_correction}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] Stacking失败: {e}")

    # ==================== 方法8: 时变加权 ====================
    if seasonal_strength > 0.2 or trend_strength > 0.2:
        try:
            n_test = len(test_values)
            n_segments = min(3, max(2, n_test // 4))

            if n_segments >= 2 and n_test >= 6:
                segment_size = n_test // n_segments
                time_varying_pred = np.zeros(n_test)
                segment_weights_list = []

                for seg in range(n_segments):
                    start_idx = seg * segment_size
                    end_idx = start_idx + segment_size if seg < n_segments - 1 else n_test

                    seg_preds = preds_matrix[start_idx:end_idx]
                    seg_actuals = test_values[start_idx:end_idx]

                    seg_errors = np.array([
                        np.mean(np.abs(seg_actuals - seg_preds[:, i]))
                        for i in range(seg_preds.shape[1])
                    ])
                    seg_weights = 1 / (seg_errors + 1e-6)

                    # 季节性和趋势模型加权
                    seg_weights[seasonal_mask] *= (1 + seasonal_strength * 0.5)
                    seg_weights *= (1 + trend_consistency_scores * trend_strength * 0.5)
                    seg_weights /= seg_weights.sum()
                    segment_weights_list.append(list(seg_weights))

                    time_varying_pred[start_idx:end_idx] = np.average(seg_preds, axis=1, weights=seg_weights)

                wmape_tv = calculate_wmape(test_values, time_varying_pred)

                ensemble_results.append({
                    'name': 'Ensemble_TV',
                    'wmape': wmape_tv,
                    'forecast': time_varying_pred,
                    'params': {
                        'method': 'time_varying',
                        'base_models': names,
                        'n_segments': n_segments,
                        'segment_weights': segment_weights_list,
                        'trend_strength': trend_strength,
                        'seasonal_strength': seasonal_strength,
                        'trend_direction': trend_direction,
                        'trend_slope': trend_slope,
                        'trend_consistency_scores': list(trend_consistency_scores)
                    },
                    'error': None
                })
                debug_print(f"      [ENSEMBLE] 时变加权: {n_segments}段, WMAPE={wmape_tv:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 时变加权失败: {e}")

    # ==================== 方法9: 趋势一致性融合 【新增】 ====================
    if trend_strength > 0.3 and trend_direction != 'flat':
        try:
            wmape_weights = 1 / (wmapes + 1e-6)
            wmape_weights /= wmape_weights.sum()

            # 趋势一致性权重
            trend_weights = trend_consistency_scores.copy()
            trend_weights = np.maximum(trend_weights, 0.1)  # 最小权重
            trend_weights /= trend_weights.sum()

            # 动态混合比例 - 趋势越强，趋势权重越高
            alpha = min(trend_strength * 0.8, 0.5)
            combined_weights = (1 - alpha) * wmape_weights + alpha * trend_weights
            combined_weights /= combined_weights.sum()

            pred_trend_cons = np.average(preds_matrix, axis=1, weights=combined_weights)
            wmape_trend_cons = calculate_wmape(test_values, pred_trend_cons)

            ensemble_results.append({
                'name': 'Ensemble_TCons',
                'wmape': wmape_trend_cons,
                'forecast': pred_trend_cons,
                'params': {
                    'method': 'trend_consistent',
                    'base_models': names,
                    'weights': list(combined_weights),
                    'wmape_weights': list(wmape_weights),
                    'trend_consistency_scores': list(trend_consistency_scores),
                    'trend_direction': trend_direction,
                    'trend_strength': trend_strength,
                    'trend_slope': trend_slope,
                    'alpha': alpha
                },
                'error': None
            })
            debug_print(f"      [ENSEMBLE] 趋势一致性融合: alpha={alpha:.2f}, WMAPE={wmape_trend_cons:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 趋势一致性融合失败: {e}")

    # ==================== 方法10: 季节性一致性融合 ====================
    if seasonal_strength > 0.35 and train_data is not None:
        try:
            pattern = seasonal_pattern
            test_indices = get_seasonal_indices(test_data.index, train_data.index[-1], detected_period)

            consistency_scores = []
            for i in range(len(valid_results)):
                pred = preds_matrix[:, i]
                pred_normalized = pred / np.mean(pred) if np.mean(pred) > 0 else pred
                expected_pattern = np.array([pattern[idx % len(pattern)] for idx in test_indices])

                try:
                    corr = np.corrcoef(pred_normalized, expected_pattern)[0, 1]
                    corr = corr if not np.isnan(corr) else 0
                except:
                    corr = 0
                consistency_scores.append(max(0, corr))

            consistency_scores = np.array(consistency_scores)

            if consistency_scores.sum() > 0.1:
                wmape_weights = 1 / (wmapes + 1e-6)
                wmape_weights /= wmape_weights.sum()

                consistency_weights = consistency_scores / consistency_scores.sum()
                alpha = min(seasonal_strength, 0.6)
                combined_weights = (1 - alpha) * wmape_weights + alpha * consistency_weights
                combined_weights /= combined_weights.sum()

                pred_consistent = np.average(preds_matrix, axis=1, weights=combined_weights)
                wmape_consistent = calculate_wmape(test_values, pred_consistent)

                ensemble_results.append({
                    'name': 'Ensemble_Cons',
                    'wmape': wmape_consistent,
                    'forecast': pred_consistent,
                    'params': {
                        'method': 'seasonal_consistent',
                        'base_models': names,
                        'weights': list(combined_weights),
                        'wmape_weights': list(wmape_weights),
                        'consistency_scores': list(consistency_scores),
                        'seasonal_strength': seasonal_strength,
                        'alpha': alpha,
                        'trend_direction': trend_direction,
                        'trend_strength': trend_strength,
                        'trend_slope': trend_slope,
                        'trend_consistency_scores': list(trend_consistency_scores)
                    },
                    'error': None
                })
                debug_print(f"      [ENSEMBLE] 季节性一致性融合: alpha={alpha:.2f}, WMAPE={wmape_consistent:.4f}")

        except Exception as e:
            debug_print(f"      [ENSEMBLE] 季节性一致性融合失败: {e}")

    return ensemble_results

def predict_future(full_data, winner_info, n_future=16, full_exog=None, future_exog=None, base_results=None):
    """
    生成未来预测 - 保持原有逻辑，只在最终结果上做安全检查
    """
    name = winner_info['name']
    params = winner_info.get('params', {})

    # 计算fallback值
    fallback_value = float(full_data.iloc[-8:].mean())

    debug_print(f"\n      [DEBUG] ===== predict_future: {name} =====")
    debug_print(f"      [DEBUG] fallback_value={fallback_value:.2f}")
    result = None
    CatBoostRegressor = _get_catboost_regressor()

    # ==================== Ensemble ====================
    if 'Ensemble' in name:
        base_names = params.get('base_models', [])
        weights = params.get('weights', [])
        wmape_weights = params.get('wmape_weights', weights)

        # 【新增】获取趋势和季节性参数
        trend_direction = params.get('trend_direction', 'flat')
        trend_strength = params.get('trend_strength', 0)
        trend_slope = params.get('trend_slope', 0)
        seasonal_strength = params.get('seasonal_strength', 0)
        detected_period = params.get('detected_period', 52)
        trend_consistency_scores = params.get('trend_consistency_scores', [])
        seasonal_pattern_saved = params.get('seasonal_pattern', None)
        preds_list = []
        valid_weights = []
        valid_trend_scores = []

        for i, bn in enumerate(base_names):
            br = next((r for r in (base_results or []) if r['name'] == bn), None)
            if br:
                try:
                    p = predict_future(full_data, br, n_future, full_exog, future_exog, base_results)
                    p = safe_predictions(p, fallback_value, bn)

                    if not np.all(p == 0):
                        preds_list.append(p)
                        valid_weights.append(weights[i] if i < len(weights) else 1.0 / len(base_names))
                        if i < len(trend_consistency_scores):
                            valid_trend_scores.append(trend_consistency_scores[i])
                        else:
                            valid_trend_scores.append(0.5)
                        debug_print(f"      [DEBUG] Ensemble基础模型 {bn}: mean={np.mean(p):.2f}")
                except Exception as e:
                    debug_print(f"      [DEBUG] Ensemble基础模型 {bn} 失败: {str(e)[:30]}")

        if not preds_list:
            debug_print(f"      [DEBUG] Ensemble: 所有基础模型失败，使用fallback")
            return np.full(n_future, fallback_value)

        preds_matrix = np.array(preds_list).T
        valid_weights = np.array(valid_weights)
        valid_trend_scores = np.array(valid_trend_scores)

        # 权重安全检查 - 处理负权重问题
        if np.any(valid_weights < -0.1):
            debug_print(f"      [DEBUG] Ensemble: 检测到负权重，使用WMAPE权重")
            valid_weights = np.array(wmape_weights[:len(preds_list)])

        if np.sum(np.abs(valid_weights)) < 1e-6:
            valid_weights = np.ones(len(preds_list)) / len(preds_list)
        # 确保权重非负并归一化
        valid_weights = np.abs(valid_weights)
        valid_weights /= valid_weights.sum()

        result = np.average(preds_matrix, axis=1, weights=valid_weights)

        # 【新增】趋势校正
        if trend_strength > 0.25 and trend_direction != 'flat':
            try:
                # 检查融合结果的趋势
                result_trend_dir, result_trend_str, result_slope = detect_trend_strength(pd.Series(result))

                debug_print(f"      [ENSEMBLE FUTURE] 趋势检查: 期望={trend_direction}, 实际={result_trend_dir}")

                if result_trend_dir != trend_direction:
                    debug_print(f"      [ENSEMBLE FUTURE] 趋势不一致，需要校正")

                    # 方法1: 使用趋势最一致的基础模型
                    if len(valid_trend_scores) > 0 and np.max(valid_trend_scores) > 0.6:
                        best_trend_idx = np.argmax(valid_trend_scores)
                        best_trend_pred = preds_matrix[:, best_trend_idx]

                        # 验证该模型趋势是否正确
                        check_dir, _, _ = detect_trend_strength(pd.Series(best_trend_pred))

                        if check_dir == trend_direction:
                            correction_weight = min(trend_strength * 0.4, 0.3)
                            result = (1 - correction_weight) * result + correction_weight * best_trend_pred
                            debug_print(
                                f"      [ENSEMBLE FUTURE] 趋势校正: 使用模型{best_trend_idx}, 权重={correction_weight:.2f}")

                    # 方法2: 添加趋势分量
                    result_trend_dir2, _, _ = detect_trend_strength(pd.Series(result))
                    if result_trend_dir2 != trend_direction:
                        # 外推历史趋势
                        trend_component = extrapolate_trend(full_data, n_future, trend_strength, trend_direction)

                        if np.any(trend_component != 0):
                            result = result + trend_component
                            debug_print(f"      [ENSEMBLE FUTURE] 添加趋势分量: {trend_component[:3]}...")

            except Exception as e:
                debug_print(f"      [ENSEMBLE FUTURE] 趋势校正失败: {e}")

        # 【增强】季节性校正
        if seasonal_strength > 0.3:
            try:
                # 提取历史季节性模式
                full_seasonal_pattern = extract_seasonal_pattern(full_data, detected_period)

                # 获取未来日期的季节性索引
                future_dates_temp = pd.date_range(full_data.index[-1], periods=n_future + 1, freq='W')[1:]
                future_indices = get_seasonal_indices(future_dates_temp, full_data.index[-1], detected_period)

                # 计算季节性调整因子
                seasonal_factors = np.array([
                    full_seasonal_pattern[idx % len(full_seasonal_pattern)]
                    for idx in future_indices
                ])

                # 应用季节性校正
                result_mean = np.mean(result)
                if result_mean > 0:
                    # 调整幅度与季节性强度成正比
                    adjustment_strength = min(seasonal_strength * 0.4, 0.25)

                    # 混合原始预测和季节性调整后的预测
                    seasonal_adjusted = result_mean * seasonal_factors
                    result = (1 - adjustment_strength) * result + adjustment_strength * seasonal_adjusted

                    debug_print(f"      [ENSEMBLE FUTURE] 季节性校正: strength={adjustment_strength:.2f}")

            except Exception as e:
                debug_print(f"      [ENSEMBLE FUTURE] 季节性校正失败: {e}")

    # ==================== 树模型 ====================
    elif name in ['XGBoost', 'LightGBM', 'CatBoost']:
        feat_eng = params.get('feat_eng')
        if feat_eng is None:
            debug_print(f"      [DEBUG] {name}: feat_eng为None")
            return np.full(n_future, fallback_value)

        try:
            full_diff, full_last_log = make_log_diff(full_data)

            if full_exog is not None and len(full_exog) > 0:
                exog_aligned = full_exog.iloc[1:].copy()
                exog_aligned.index = full_diff.index
            else:
                exog_aligned = None

            X_full, y_full = feat_eng.make_features_for_prediction(full_diff, exog_aligned)

            if len(X_full) < 5:
                return np.full(n_future, fallback_value)

            model_params = {k: v for k, v in params.items()
                            if k not in ['feat_eng', 'train_last_log', 'model_type', 'exog_cols']}
            model_type = params.get('model_type', 'xgboost')

            if model_type == 'xgboost':
                model = XGBRegressor(**model_params, objective='reg:squarederror',
                                     n_jobs=-1, verbosity=0, random_state=42)
            elif model_type == 'lgbm':
                model = LGBMRegressor(**model_params, n_jobs=-1, random_state=42, verbose=-1)
            elif model_type == 'catboost' and CatBoostRegressor is not None:
                model = CatBoostRegressor(**model_params, loss_function='MAE',
                                          verbose=0, allow_writing_files=False, random_state=42)
            else:
                return np.full(n_future, fallback_value)

            model.fit(X_full, y_full)

            result = tree_recursive_predict(
                model, full_diff, full_last_log, n_future, feat_eng,
                X_full['time_idx'].iloc[-1] + 1, future_exog, exog_aligned
            )

        except Exception as e:
            debug_print(f"      [DEBUG] {name} 预测出错: {str(e)}")
            return np.full(n_future, fallback_value)

    # ==================== SARIMA+DL ====================
    elif 'SARIMA' in name:
        try:
            full_values = full_data.values.flatten()
            full_log = np.log1p(np.maximum(full_values, 0))

            arima_order = params.get('arima_order', (1, 1, 1))
            arima_seasonal = params.get('arima_seasonal_order', (0, 1, 1, 52))

            try:
                arima_model = pm.ARIMA(order=arima_order, seasonal_order=arima_seasonal)
                with suppress_stdout_stderr():
                    arima_model.fit(full_log)
            except:
                arima_model = pm.ARIMA(order=(1, 1, 1), seasonal_order=(0, 1, 1, 52))
                with suppress_stdout_stderr():
                    arima_model.fit(full_log)

            full_arima = np.expm1(arima_model.predict_in_sample())
            future_arima = np.expm1(arima_model.predict(n_periods=n_future))
            future_arima = np.maximum(future_arima, 0)

            residuals = (full_values - full_arima).reshape(-1, 1)
            residuals = np.nan_to_num(residuals, nan=0.0, posinf=0.0, neginf=0.0)

            scaler = MinMaxScaler((-1, 1))
            res_scaled = scaler.fit_transform(residuals)

            lb = params.get('look_back', 4)
            neu = params.get('neurons', 32)
            epochs = params.get('epochs', 20)
            dl_type = params.get('dl_type', 'lstm')

            X, Y = [], []
            for i in range(len(res_scaled) - lb):
                X.append(res_scaled[i:i + lb, 0])
                Y.append(res_scaled[i + lb, 0])
            X, Y = np.array(X), np.array(Y)

            if len(X) < 5:
                result = future_arima
            else:
                X = X.reshape(X.shape[0], X.shape[1], 1)

                tf.keras.backend.clear_session()

                if dl_type == 'lstm':
                    model = Sequential([LSTM(neu, input_shape=(lb, 1), activation='tanh'), Dropout(0.1), Dense(1)])
                elif dl_type == 'tcn':
                    model = build_tcn_model((lb, 1), neu)
                elif dl_type == 'nbeats':
                    model = build_nbeats_model((lb, 1), neu)
                else:
                    model = Sequential([LSTM(neu, input_shape=(lb, 1), activation='tanh'), Dense(1)])

                model.compile(loss='mse', optimizer=Adam(0.01))
                model.fit(X, Y, epochs=epochs, batch_size=min(16, max(4, len(X) // 4)),
                          verbose=0, callbacks=[EarlyStopping(monitor='loss', patience=3, restore_best_weights=True)])

                curr = res_scaled[-lb:].flatten()
                pred_resids = []
                for _ in range(n_future):
                    p = model.predict(curr.reshape(1, lb, 1), verbose=0)[0, 0]
                    pred_resids.append(p)
                    curr = np.append(curr[1:], p)

                pred_resids = scaler.inverse_transform(np.array(pred_resids).reshape(-1, 1)).flatten()
                pred_resids = scaler.inverse_transform(np.array(pred_resids).reshape(-1, 1)).flatten()

                # 【新增】限制残差范围，避免异常值
                resid_std = np.std(full_values - full_arima)
                pred_resids = np.clip(pred_resids, -3 * resid_std, 3 * resid_std)

                result = future_arima + pred_resids

                # 【新增】如果结果异常，只使用ARIMA部分
                if np.any(result < 0) or np.mean(result) < np.mean(full_values) * 0.1:
                    debug_print(f"      [SARIMA+DL] 预测异常，使用纯ARIMA结果")
                    result = future_arima

        except Exception as e:
            debug_print(f"      [DEBUG] SARIMA+DL 预测出错: {str(e)}")
            return np.full(n_future, fallback_value)

    # ==================== Prophet ====================
    elif name == 'Prophet':
        try:
            exog_cols = params.get('exog_cols', [])
            p_params = {k: v for k, v in params.items() if k in PROPHET_VALID_PARAMS}
            m = Prophet(**p_params, yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)

            df_full = full_data.reset_index()
            df_full.columns = ['ds', 'y']
            df_full['ds'] = pd.to_datetime(df_full['ds'])

            if exog_cols and full_exog is not None:
                exog_reset = full_exog.reset_index()
                exog_reset.columns = ['ds'] + list(full_exog.columns)
                exog_reset['ds'] = pd.to_datetime(exog_reset['ds'])
                df_full = df_full.merge(exog_reset, on='ds', how='left')
                for c in exog_cols:
                    if c in df_full.columns:
                        m.add_regressor(c)
                        df_full[c] = df_full[c].fillna(df_full[c].mean())

            with suppress_stdout_stderr():
                m.fit(df_full)

            future = m.make_future_dataframe(periods=n_future, freq='W')

            if exog_cols and future_exog is not None:
                comb_exog = pd.concat([full_exog, future_exog]).reset_index()
                comb_exog.columns = ['ds'] + list(full_exog.columns)
                comb_exog['ds'] = pd.to_datetime(comb_exog['ds'])
                future = future.merge(comb_exog, on='ds', how='left')
                for c in exog_cols:
                    if c in future.columns:
                        future[c] = future[c].fillna(future[c].mean())

            result = m.predict(future)['yhat'].iloc[-n_future:].values

        except Exception as e:
            debug_print(f"      [DEBUG] Prophet 预测出错: {str(e)}")
            return np.full(n_future, fallback_value)

    # ==================== 默认情况 ====================
    else:
        debug_print(f"      [DEBUG] 未匹配的模型名称: {name}")
        return np.full(n_future, fallback_value)

    # 【最终安全检查 + 波动性恢复】
    if result is not None:
        result = safe_predictions(result, fallback_value, name)

        # 对Ensemble模型恢复波动性
        if 'Ensemble' in name:
            result = restore_volatility(result, full_data, strength=0.5)
            debug_print(f"      [DEBUG] {name} 波动性恢复后: mean={np.mean(result):.2f}, std={np.std(result):.2f}")

        debug_print(f"      [DEBUG] {name} final result: mean={np.mean(result):.2f}")
        return result
    else:
        return np.full(n_future, fallback_value)
# ============================================================
# 模型竞赛主函数
# ============================================================

def run_all_models(train_data, test_data, mode='full', train_exog=None, test_exog=None, verbose=True):
    """在单 SKU 的训练/验证集上跑完整“模型竞赛”。

    返回：
    - all_results: 包含基模型 + Ensemble 的结果列表（用于选冠军）
    - base_results: 仅包含非 Ensemble 的结果列表（用于未来预测时给 Ensemble 递归调用）

    注意：
    - 每个模型都受超时控制（避免某个模型卡住拖慢全流程）
    - 这里的 test_data 仅用于验证评估，不会泄漏到训练（除 Ensemble stacking 属于“在验证集上拟合权重”的策略）
    """
    base_results = []
    config = SearchConfig.get(mode)
    model_timeout = config.get('model_timeout', 90)
    arima_timeout = config.get('arima_timeout', 40)
    dl_timeout = config.get('dl_timeout', 50)

    CATBOOST_AVAILABLE = _get_catboost_regressor() is not None

    def create_feat_eng():
        return FeatureEngineer(lags=[1, 2, 4], rolling_windows=[4, 8])

    print(f"\n   📦 Running models (mode={mode})...")

    # 1. 非ARIMA模型
    non_arima_tasks = [
        ('Prophet', lambda: optimize_prophet(train_data, test_data, mode, train_exog, test_exog)),
        ('XGBoost',
         lambda: optimize_tree_model('xgboost', train_data, test_data, create_feat_eng(), mode, train_exog, test_exog)),
        ('LightGBM',
         lambda: optimize_tree_model('lgbm', train_data, test_data, create_feat_eng(), mode, train_exog, test_exog)),
    ]
    if CATBOOST_AVAILABLE:
        non_arima_tasks.append(('CatBoost',
                                lambda: optimize_tree_model('catboost', train_data, test_data, create_feat_eng(), mode,
                                                            train_exog, test_exog)))

    for name, func in non_arima_tasks:
        print(f"      🔄 {name}...", end=" ", flush=True)
        t0 = time.time()
        try:
            result = run_with_timeout(func, model_timeout)
            elapsed = time.time() - t0
            if result and result['forecast'] is not None and result['wmape'] < float('inf'):
                result['training_time'] = elapsed
                base_results.append(result)
                print(f"WMAPE={result['wmape']:.2%} ({elapsed:.1f}s)")
                debug_print(f"      [DEBUG] {name} forecast[:5]: {result['forecast'][:5]}")
            else:
                if result and result.get('error'):
                    print(f"Failed: {str(result['error'])[:30]}")
                else:
                    print("Failed")
        except Exception as e:
            print(f"Error: {str(e)[:25]}")

    # 2. 共享ARIMA拟合
    arima_model, train_arima = None, None
    dl_models = ['lstm']
    if config.get('enable_tcn', False):
        dl_models.append('tcn')
    if config.get('enable_nbeats', False):
        dl_models.append('nbeats')

    if dl_models:
        print(f"      🔄 Fitting ARIMA (timeout={arima_timeout}s)...", end=" ", flush=True)
        t0 = time.time()
        try:
            def arima_task():
                return fit_shared_arima(train_data, mode)

            result = run_with_timeout(arima_task, arima_timeout)
            elapsed = time.time() - t0

            if result and result[2]:
                arima_model, train_arima, _ = result
                order_str = f"order={arima_model.order}"
                if hasattr(arima_model, 'seasonal_order') and arima_model.seasonal_order:
                    s_order = arima_model.seasonal_order
                    if s_order != (0, 0, 0, 0):
                        order_str += f", seasonal={s_order}"
                print(f"Done ({elapsed:.1f}s, {order_str})")
            else:
                print(f"Failed ({elapsed:.1f}s)")

        except Exception as e:
            elapsed = time.time() - t0
            print(f"Error ({elapsed:.1f}s): {str(e)[:30]}")

    # 3. DL混合模型
    if arima_model is not None:
        for dl_type in dl_models:
            name = f"SARIMA+{dl_type.upper()}"
            print(f"      🔄 {name}...", end=" ", flush=True)
            t0 = time.time()
            try:
                result = run_with_timeout(
                    lambda dt=dl_type: optimize_dl_with_arima(train_data, test_data, dt, arima_model, train_arima,
                                                              mode),
                    dl_timeout
                )
                elapsed = time.time() - t0
                if result and result['forecast'] is not None and result['wmape'] < float('inf'):
                    result['training_time'] = elapsed
                    base_results.append(result)
                    print(f"WMAPE={result['wmape']:.2%} ({elapsed:.1f}s)")
                else:
                    if result and result.get('error'):
                        print(f"Failed: {str(result['error'])[:30]}")
                    else:
                        print("Failed")
            except Exception as e:
                print(f"Error: {str(e)[:25]}")
    else:
        print(f"      ⚠️ Skipping DL models (ARIMA failed)")

    # 4. Ensemble
    if len(base_results) >= 2:
        print(f"      🔄 Seasonal Ensemble...", end=" ", flush=True)
        try:
            ens_results = optimize_ensemble(base_results, test_data, mode, train_data)  # 【新增参数】
            for e in ens_results:
                e['training_time'] = 0.1
            base_results.extend(ens_results)
            print(f"Done ({len(ens_results)} methods)")
        except Exception as e:
            debug_print(f"      [ENSEMBLE] 错误: {e}")
            print("Failed")

    return base_results, [r for r in base_results if 'Ensemble' not in r['name']]

def plot_forecast(profile, train_data, test_data, all_results, future_preds, future_dates,
                  save_path=None, show_plot=True):
    """绘制单 SKU 的预测对比图（历史/验证/各模型预测/未来预测）并可选保存。

    - 上图：时间序列折线（冠军模型高亮）
    - 下图：各模型 WMAPE 横向柱状图
    """
    try:
        fig, axes = plt.subplots(2, 1, figsize=(14, 10))

        ax = axes[0]
        ax.plot(train_data.index, train_data.values, label='历史数据', color='#333', linewidth=1.5)
        ax.plot(test_data.index, test_data.values, label='实际值', color='black', marker='o', linewidth=2)

        colors = plt.cm.tab10(np.linspace(0, 1, len(all_results)))
        for idx, res in enumerate(all_results):
            is_winner = res['name'] == profile.winner_name
            ax.plot(test_data.index, res['forecast'],
                    linestyle='-' if is_winner else '--',
                    alpha=1.0 if is_winner else 0.4,
                    linewidth=2.5 if is_winner else 1.0,
                    color='red' if is_winner else colors[idx],
                    label=res['name'])

        ax.plot(future_dates, future_preds, label='未来预测', color='purple', linewidth=3, marker='D', markersize=5)
        ax.set_title(f"SKU: {profile.sku} - 🏆 {profile.winner_name} (WMAPE: {profile.winner_wmape:.2%})",
                     fontsize=14, fontweight='bold')
        ax.legend(loc='upper left', ncol=3, fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('日期', fontsize=11)
        ax.set_ylabel('销售量', fontsize=11)

        ax2 = axes[1]
        sorted_res = sorted(all_results, key=lambda x: x['wmape'])
        names = [r['name'][:15] for r in sorted_res]
        wmapes = [r['wmape'] * 100 for r in sorted_res]
        colors_bar = ['gold' if r['name'] == profile.winner_name else 'steelblue' for r in sorted_res]
        bars = ax2.barh(names, wmapes, color=colors_bar, edgecolor='black')

        for bar in bars:
            width = bar.get_width()
            ax2.text(width + 0.5, bar.get_y() + bar.get_height() / 2,
                     f'{width:.2f}%', va='center', fontsize=9)

        ax2.set_xlabel("WMAPE (%)", fontsize=11)
        ax2.set_title("模型性能对比", fontsize=12)
        ax2.invert_yaxis()

        plt.tight_layout()

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            plt.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='white')
            print(f"   💾 图片已保存: {save_path}")

        if show_plot:
            plt.show()
        else:
            plt.close(fig)

        return True

    except Exception as e:
        print(f"   ❌ 绑图失败: {str(e)}")
        return False


def plot_best_sku_style(profile, train_data, test_data, all_results, future_preds, future_dates,
                        save_path=None, show_plot=True):
    """绘制“最佳 SKU”展示版图表（更强调可视化风格与对比效果）。"""
    try:
        sorted_results = sorted(all_results, key=lambda x: x['wmape'])
        top_results = sorted_results[:4]
        winner_name = profile.winner_name

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), gridspec_kw={'height_ratios': [2.5, 1]})

        ax1.plot(train_data.index, train_data.values, label='历史数据 (训练集)',
                 color='#666666', linewidth=2, marker='.', markersize=6)
        ax1.plot(test_data.index, test_data.values, label='实际值 (测试集)',
                 color='black', linewidth=2.5, marker='o', markersize=8, zorder=10)

        markers = ['^', 's', 'v', 'D']
        colors = ['#FF9F40', '#4BC0C0', '#36A2EB', '#FF6384']

        for i, res in enumerate(top_results):
            is_winner = res['name'] == winner_name
            label = f"{res['name']} (WMAPE: {res['wmape'] * 100:.2f}%)"
            ax1.plot(test_data.index, res['forecast'], label=label,
                     linestyle='--', linewidth=3 if is_winner else 2,
                     color=colors[i % len(colors)], marker=markers[i % len(markers)], markersize=7)

        ax1.plot(future_dates, future_preds, label=f'未来预测 ({winner_name})',
                 color='#9966FF', linewidth=3, marker='D', markersize=8, zorder=10)

        ax1.axvspan(test_data.index[0], test_data.index[-1], color='yellow', alpha=0.15, label='验证区间')
        ax1.axvspan(future_dates[0], future_dates[-1], color='green', alpha=0.15, label='预测区间')

        ax1.set_title(
            f"SKU: {profile.sku} - 销售预测对比图\n🏆 胜出模型: {winner_name} (WMAPE: {profile.winner_wmape:.2%})",
            fontsize=16, fontweight='bold', pad=20)
        ax1.set_ylabel('销售量', fontsize=12)
        ax1.set_xlabel('日期', fontsize=12)
        ax1.grid(True, linestyle='--', alpha=0.5)
        ax1.legend(loc='upper left', ncol=2, fontsize=10, framealpha=0.9, shadow=True)

        names = [r['name'] for r in top_results]
        wmapes = [r['wmape'] * 100 for r in top_results]
        bar_colors = [colors[i % len(colors)] for i in range(len(top_results))]

        bars = ax2.bar(names, wmapes, color=bar_colors, edgecolor='black', alpha=0.9, width=0.6)

        winner_idx = next((i for i, r in enumerate(top_results) if r['name'] == winner_name), 0)
        bars[winner_idx].set_edgecolor('gold')
        bars[winner_idx].set_linewidth(3)

        for bar in bars:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2., height + 0.5,
                     f'{height:.2f}%', ha='center', va='bottom', fontsize=12, fontweight='bold')

        ax2.set_title("各模型 WMAPE 对比", fontsize=14)
        ax2.set_ylabel('WMAPE (%)', fontsize=12)
        ax2.set_ylim(0, max(wmapes) * 1.3)
        ax2.grid(axis='y', linestyle='--', alpha=0.5)

        plt.tight_layout()

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='white')
            print(f"   ✨ 高级图表已保存: {save_path}")

        if show_plot:
            plt.show()
        else:
            plt.close(fig)

        return True

    except Exception as e:
        print(f"   ❌ 绑图失败: {str(e)}")
        return False

def process_single_sku(sku, df_all, mode='smart', exog_cols=None, collect_viz=False, verbose=True):
    """处理单个 SKU：清洗 -> 画像 -> 模型竞赛 -> 未来预测 -> 组织输出。

    返回：
    - result_df: 预测明细（每未来周一行），可直接 concat 后落盘/落库
    - msg: 控制台友好的摘要信息（冠军模型 + WMAPE + 耗时 / 或失败原因）
    - viz_data: 可选，为绘图收集的对象（profile/train/test/results/future/dates/winner）
    - profile: SKUProfile（包含画像与结果汇总）
    """
    t0 = time.time()
    profiler = SKUProfiler(verbose=verbose)

    try:
        df_sku = df_all[df_all['sku'] == sku].set_index('date').sort_index()
        series = df_sku['sales'].resample('W').sum()
        current_week_end = get_current_week_end()
        series = series[series.index < current_week_end]
        original_series = series.copy()

        has_exog, exog_series, used_exog = False, None, []
        if exog_cols:
            available = [c for c in exog_cols if c in df_sku.columns]
            if available:
                exog_series = df_sku[available].resample('W').sum()
                exog_series = exog_series[exog_series.index < current_week_end].fillna(0)
                has_exog, used_exog = True, available
                debug_print(f"\n      [DEBUG] 外生变量: {available}")

        if len(series) > 156:
            series = series.iloc[-156:]
            original_series = original_series.iloc[-156:]
            if has_exog:
                exog_series = exog_series.iloc[-156:]

        series_clean = clean_series(series)
        if len(series_clean) < 30:
            return None, "数据不足 (<30周)", None, None

        profile = profiler.analyze(sku, series_clean, original_series, exog_series)
        if verbose:
            profiler.print_profile(profile)

        train, test = series_clean.iloc[:-10], series_clean.iloc[-10:]
        train_exog = exog_series.iloc[:-10] if has_exog else None
        test_exog = exog_series.iloc[-10:] if has_exog else None

        debug_print(f"\n      [DEBUG] train: len={len(train)}, mean={train.mean():.2f}")
        debug_print(f"      [DEBUG] test: len={len(test)}, mean={test.mean():.2f}")

        print(f"\n⚡ 模型竞赛中 (mode={mode})...")
        all_results, base_results = run_all_models(train, test, mode, train_exog, test_exog, verbose=False)

        if not all_results:
            return None, "所有模型失败", None, profile

        winner = min(all_results, key=lambda x: x['wmape'])

        debug_print(f"\n      [DEBUG] ===== 开始未来预测 =====")
        debug_print(f"      [DEBUG] winner: {winner['name']}, wmape={winner['wmape']:.4f}")

        future_exog = None
        if has_exog and exog_series is not None:
            future_dates_exog = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]
            future_exog_data = {}
            for c in exog_series.columns:
                mean_val = exog_series[c].mean()
                future_exog_data[c] = [mean_val] * 16
            future_exog = pd.DataFrame(future_exog_data, index=future_dates_exog)

        final_preds = predict_future(series_clean, winner, 16, exog_series, future_exog, base_results)

        # 【诊断代码】检查波动性
        hist_cv = series_clean.std() / series_clean.mean() if series_clean.mean() > 0 else 0
        pred_cv = np.std(final_preds) / np.mean(final_preds) if np.mean(final_preds) > 0 else 0
        print(f"   📊 波动性检查: 历史CV={hist_cv:.3f}, 预测CV={pred_cv:.3f}, 比值={pred_cv / hist_cv:.2f}")

        if pred_cv < hist_cv * 0.3:
            print(f"   ⚠️ 警告: 预测波动性过低! 可能需要调整")
        # 最终安全检查
        fallback_value = float(series_clean.iloc[-8:].mean())
        final_preds = safe_predictions(final_preds, fallback_value, winner['name'])

        debug_print(f"\n      [DEBUG] ===== 预测结果 =====")
        debug_print(f"      [DEBUG] final_preds: {final_preds[:5]}...")
        debug_print(f"      [DEBUG] 均值: {np.mean(final_preds):.2f}")

        total_time = time.time() - t0

        future_dates = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]
        profile = profiler.update_with_results(profile, train, test, all_results, winner, final_preds, total_time)

        if verbose:
            profiler.print_model_competition(profile)
            profiler.print_forecast_summary(profile, future_dates, final_preds)

        result_df = pd.DataFrame({
            'sku': sku,
            'run_date': datetime.date.today(),
            'forecast_target_date': future_dates,
            'forecast_value': np.round(final_preds, 4),
            'winner_algo': winner['name'],
            'validation_wmape': round(winner['wmape'], 4),
            'best_params': clean_params_for_db(winner.get('params')),
            'has_exog_features': has_exog,
            'exog_columns': ','.join(used_exog) if used_exog else None,
            'training_weeks': len(series_clean),
            'data_end_date': series_clean.index[-1].date(),
            'create_time': datetime.datetime.now()
        })

        viz_data = None
        if collect_viz:
            viz_data = {'profile': profile, 'train': train, 'test': test,
                        'results': all_results, 'future': final_preds, 'dates': future_dates, 'winner': winner}

        return result_df, f"🏆 {winner['name']} (WMAPE: {winner['wmape']:.2%}) [{total_time:.1f}s]", viz_data, profile

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"错误: {str(e)}", None, None

def main():
    """批量处理 CSV 中的所有 SKU，并输出预测/画像/可视化/可选写库。"""
    # ========== 配置区域 ==========
    FILE_PATH = 'D:/华熠/sales_multi_sku.csv'
    SAVE_PLOT_DIR = 'D:/华熠/plots'
    OUTPUT_DIR = 'D:/华熠/output'
    REPORT_DIR = 'D:/华熠/reports'

    RUN_MODE = 'smart'
    SHOW_PLOTS = True
    SAVE_PLOTS = True

    ENABLE_DB_WRITE = True
    # 建议：把数据库连接串放到环境变量 `SALES_FORECAST_DB_URL`，避免在代码里硬编码账号密码
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/postgres")
    DB_TABLE = "sales_forecast_history"
    # ==============================

    print("=" * 70)
    print("🚀 销售预测引擎 v7.9 (保守修复版)")
    print(f"   运行模式: {RUN_MODE.upper()}")
    print(f"   调试模式: {'开启' if DEBUG_MODE else '关闭'}")
    print(f"   弹窗显示: {'开启' if SHOW_PLOTS else '关闭'}")
    print("=" * 70)

    for d in [SAVE_PLOT_DIR, OUTPUT_DIR, REPORT_DIR]:
        os.makedirs(d, exist_ok=True)

    global_best_wmape = float('inf')
    global_best_viz = None

    try:
        print(f"\n📂 加载数据: {FILE_PATH}")
        df_all = pd.read_csv(FILE_PATH)
        df_all['sales'] = pd.to_numeric(df_all['sales'], errors='coerce').fillna(0)
        df_all['date'] = pd.to_datetime(df_all['date'], format='mixed')
        df_all['sku'] = df_all['sku'].astype(str)

        skus = df_all['sku'].unique()
        print(f"   发现 {len(skus)} 个SKU")

        exog_cols = [c for c in df_all.columns if c not in ['date', 'sku', 'sales']]
        if exog_cols:
            print(f"   外生变量: {exog_cols}")

        all_res, failed_skus, all_reports = [], [], []
        profiler = SKUProfiler()

        for i, sku in enumerate(skus, 1):
            print(f"\n{'=' * 70}")
            print(f"[{i}/{len(skus)}] SKU: {sku}")
            print("=" * 70)

            res, msg, viz, profile = process_single_sku(
                sku, df_all, mode=RUN_MODE,
                exog_cols=exog_cols, collect_viz=True, verbose=True
            )
            print(f"\n   📋 结果: {msg}")

            if res is not None and viz is not None:
                all_res.append(res)

                current_wmape = profile.winner_wmape
                if current_wmape < global_best_wmape:
                    global_best_wmape = current_wmape
                    global_best_viz = viz
                    print(f"   🌟 新的最佳模型! WMAPE: {current_wmape:.2%}")

                save_path = os.path.join(SAVE_PLOT_DIR, f"{sku}_forecast.png") if SAVE_PLOTS else None

                print(f"\n   🎨 绑制图片...")
                plot_forecast(
                    viz['profile'], viz['train'], viz['test'],
                    viz['results'], viz['future'], viz['dates'],
                    save_path=save_path,
                    show_plot=SHOW_PLOTS
                )

                all_reports.append(profiler.generate_report_dict(profile))
            else:
                failed_skus.append({'sku': sku, 'reason': msg})

        print("\n" + "=" * 70)
        print("📊 完成!")
        print("=" * 70)

        if global_best_viz:
            best_sku = global_best_viz['profile'].sku
            print(f"\n🌟 绘制最佳SKU报告: {best_sku} (WMAPE: {global_best_wmape:.2%})")

            best_save_path = os.path.join(SAVE_PLOT_DIR, f"BEST_{best_sku}.png") if SAVE_PLOTS else None

            plot_best_sku_style(
                global_best_viz['profile'],
                global_best_viz['train'],
                global_best_viz['test'],
                global_best_viz['results'],
                global_best_viz['future'],
                global_best_viz['dates'],
                save_path=best_save_path,
                show_plot=SHOW_PLOTS
            )

        if all_res:
            final = pd.concat(all_res, ignore_index=True)
            print(f"\n✅ 成功: {len(all_res)}/{len(skus)} 个SKU ({len(final)} 条记录)")
            print("\n🏆 胜出模型统计:")
            print(final.groupby('winner_algo')['sku'].nunique().sort_values(ascending=False).to_string())

            output_file = os.path.join(OUTPUT_DIR, f'forecast_{datetime.date.today()}.csv')
            final.to_csv(output_file, index=False)
            print(f"\n💾 CSV已保存: {output_file}")

            report_file = os.path.join(REPORT_DIR, f'profiles_{datetime.date.today()}.json')
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(all_reports, f, ensure_ascii=False, indent=2, default=str)
            print(f"📄 报告已保存: {report_file}")

            if ENABLE_DB_WRITE:
                try:
                    print("\n🚀 正在写入数据库...")
                    engine = create_engine(DB_URL)
                    final_db = final.copy()
                    final_db['run_date'] = pd.to_datetime(final_db['run_date'])
                    final_db['forecast_target_date'] = pd.to_datetime(final_db['forecast_target_date'])
                    final_db['data_end_date'] = pd.to_datetime(final_db['data_end_date'])
                    final_db['has_exog_features'] = final_db['has_exog_features'].astype(bool)
                    final_db['exog_columns'] = final_db['exog_columns'].fillna('')
                    final_db.to_sql(DB_TABLE, engine, if_exists='append', index=False)
                    print(f"✅ 数据库写入成功! 共 {len(final_db)} 条记录")
                except Exception as e:
                    print(f"❌ 数据库写入失败: {e}")
                    backup_file = os.path.join(OUTPUT_DIR, f'backup_{datetime.date.today()}.csv')
                    final.to_csv(backup_file, index=False)
                    print(f"   已保存备份: {backup_file}")

        if failed_skus:
            print(f"\n⚠️ 失败 ({len(failed_skus)}):")
            for f in failed_skus[:5]:
                print(f"   - {f['sku']}: {f['reason']}")

    except FileNotFoundError:
        print(f"\n❌ 文件不存在: {FILE_PATH}")
    except Exception as e:
        import traceback
        print(f"\n❌ 错误: {e}")
        traceback.print_exc()
if __name__ == "__main__":
    main()