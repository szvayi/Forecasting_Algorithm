import pandas as pd
import numpy as np
import pmdarima as pm
import json
import sys
try:
    from prophet import Prophet
except Exception:  # pragma: no cover - runtime fallback for envs without prophet
    Prophet = None
from sklearn.preprocessing import MinMaxScaler
from sklearn.linear_model import Ridge
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
import itertools
import time
import random
from functools import lru_cache, partial
from src.forecasting.models import *

forecast_kernel = None
MAX_WMAPE_CAP = 9.999
ENSEMBLE_GUARDRAIL_WMAPE_DELTA = 0.015
ENSEMBLE_GUARDRAIL_P95_FACTOR = 1.10
ENSEMBLE_GUARDRAIL_P95_DELTA = 0.02
ENSEMBLE_GUARDRAIL_OVER_RATIO_DELTA = 0.03
_PROPHET_RUNTIME_FAILURES = 0
_PROPHET_LAST_FAILURE_REASON = ""
_PROPHET_RUNTIME_FAILURE_LIMIT = 5
_PROPHET_CIRCUIT_OPEN_UNTIL = 0.0
_PROPHET_CIRCUIT_COOLDOWN_SEC = 900


def _series_to_float_series(series):
    return pd.Series(series).astype(float).replace([np.inf, -np.inf], np.nan).dropna()


def _infer_model_regime(train, screening=None):
    clean = _series_to_float_series(train)
    history_weeks = len(clean)
    recent = clean.tail(min(12, history_weeks))
    recent_zero_weeks = int((recent == 0).sum()) if len(recent) > 0 else 0
    recent_mean = float(recent.mean()) if len(recent) > 0 else 0.0
    prior = clean.iloc[:-len(recent)] if history_weeks > len(recent) else pd.Series(dtype=float)
    prior_mean = float(prior.mean()) if len(prior) > 0 else 0.0
    zero_ratio = float((clean == 0).mean()) if history_weeks > 0 else 1.0

    if screening is not None:
        recent_zero_weeks = int(screening.get("recent_zero_weeks", recent_zero_weeks))
        recent_mean = float(screening.get("recent_mean", recent_mean))
        prior_mean = float(screening.get("prior_mean", prior_mean))
        zero_ratio = float(screening.get("zero_ratio", zero_ratio))

    return {
        "history_weeks": history_weeks,
        "recent_zero_weeks": recent_zero_weeks,
        "recent_mean": recent_mean,
        "prior_mean": prior_mean,
        "zero_ratio": zero_ratio,
        "seasonal_ready": history_weeks >= 52,
        "stable": history_weeks >= 26 and zero_ratio < 0.35,
        "zero_heavy": zero_ratio >= 0.5 or recent_zero_weeks >= 4,
    }


def _build_zero_aware_forecast(train, n_steps, screening=None):
    clean = _series_to_float_series(train)
    if clean.empty:
        return np.zeros(n_steps)

    regime = _infer_model_regime(clean, screening)
    recent = clean.tail(min(12, len(clean)))
    recent_non_zero = recent[recent > 0]
    anchor = float(recent_non_zero.median()) if not recent_non_zero.empty else float(recent.mean())
    anchor = max(anchor, 0.0)

    if regime["zero_heavy"] or (screening and screening.get("recommendation") == "zero_override"):
        if regime["recent_zero_weeks"] >= 4 or regime["recent_mean"] == 0:
            return np.zeros(n_steps)
        decay = np.linspace(1.0, 0.25, n_steps)
        return np.maximum(anchor * decay, 0.0)

    if len(clean) >= 52:
        season = clean.iloc[-52:].to_numpy()
        seasonal = np.resize(season, n_steps)
        blended = 0.65 * seasonal + 0.35 * anchor
        return np.maximum(blended, 0.0)

    return np.maximum(np.full(n_steps, anchor), 0.0)


def _get_forecast_kernel():
    if forecast_kernel is not None:
        return forecast_kernel
    from src.forecasting import kernel as loaded_kernel

    return loaded_kernel


@lru_cache(maxsize=1)
def _check_prophet_runtime():
    """Preflight Prophet runtime once to avoid repeated per-SPU hard failures."""
    if Prophet is None:
        return False, "prophet_not_installed"
    try:
        test_df = pd.DataFrame(
            {
                "ds": pd.date_range("2024-01-07", periods=20, freq="W"),
                "y": np.linspace(10.0, 30.0, 20),
            }
        )
        model = Prophet(
            weekly_seasonality=False,
            yearly_seasonality=False,
            daily_seasonality=False,
        )
        model.fit(test_df)
        model.predict(test_df.tail(2))
        return True, "ok"
    except Exception as exc:
        # Some runtime environments report transient/backend-attribute errors
        # in preflight but still work in real per-SPU execution. Treat these
        # as soft-check failures and allow runtime attempts.
        msg = str(exc)
        soft_markers = ("stan_backend", "cmdstan", "pystan")
        if any(marker in msg.lower() for marker in soft_markers):
            return True, f"soft_check:{msg}"
        return False, msg


def clean_series(series):
    series = series.copy()
    series = series[series >= 0]
    Q1 = series.quantile(0.25)
    Q3 = series.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    series = series[(series >= lower_bound) & (series <= upper_bound)]
    series = series.fillna(0)
    return series


def get_current_week_end():
    today = pd.Timestamp.today()
    return today - pd.Timedelta(days=today.weekday() + 1)


def calculate_wmape(y_true, y_pred, min_non_zero_points=1):
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    min_length = min(len(y_true), len(y_pred))
    y_true = y_true[:min_length]
    y_pred = y_pred[:min_length]
    mask = y_true != 0
    if np.count_nonzero(mask) < min_non_zero_points:
        return MAX_WMAPE_CAP if min_non_zero_points > 1 else 0.0
    denominator = np.sum(np.abs(y_true[mask]))
    if denominator == 0:
        return MAX_WMAPE_CAP if min_non_zero_points > 1 else 0.0
    value = np.sum(np.abs(y_true[mask] - y_pred[mask])) / denominator
    if not np.isfinite(value):
        return MAX_WMAPE_CAP
    return float(min(value, MAX_WMAPE_CAP))


def _safe_nonzero_mean(values):
    arr = np.asarray(values, dtype=float).flatten()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 1.0
    nz = arr[np.abs(arr) > 1e-9]
    if nz.size == 0:
        return max(float(np.mean(np.abs(arr))), 1.0)
    return max(float(np.mean(np.abs(nz))), 1.0)


def _compute_prediction_quality(y_true, y_pred):
    actual = np.asarray(y_true, dtype=float).flatten()
    pred = np.asarray(y_pred, dtype=float).flatten()
    n = min(len(actual), len(pred))
    if n == 0:
        return {"quality_score": float("inf")}
    actual = actual[:n]
    pred = np.maximum(pred[:n], 0.0)

    scale = _safe_nonzero_mean(actual)
    mae_scaled = float(np.mean(np.abs(actual - pred)) / scale)
    mean_actual = float(np.mean(actual)) if n > 0 else 0.0
    mean_pred = float(np.mean(pred)) if n > 0 else 0.0
    over_bias = max(mean_pred - mean_actual, 0.0) / max(scale, 1.0)

    actual_zero_ratio = float(np.mean(actual <= 1e-9))
    pred_zero_ratio = float(np.mean(pred <= 1e-9))
    zero_mismatch = abs(actual_zero_ratio - pred_zero_ratio)

    actual_diff = np.diff(actual) if n > 1 else np.array([0.0])
    pred_diff = np.diff(pred) if n > 1 else np.array([0.0])
    actual_vol = float(np.mean(np.abs(actual_diff)))
    pred_vol = float(np.mean(np.abs(pred_diff)))
    volatility_gap = abs(pred_vol - actual_vol) / max(scale, 1.0)

    mask_non_zero = actual > 1e-9
    if np.any(mask_non_zero):
        ape = np.abs(actual[mask_non_zero] - pred[mask_non_zero]) / np.maximum(np.abs(actual[mask_non_zero]), 1e-9)
        p90_ape = float(np.percentile(ape, 90))
        p95_ape = float(np.percentile(ape, 95))
        over_forecast_rate = float(np.mean((pred[mask_non_zero] - actual[mask_non_zero]) > 0))
        over_forecast_ratio = float(
            np.sum(np.maximum(pred[mask_non_zero] - actual[mask_non_zero], 0.0))
            / np.sum(np.abs(actual[mask_non_zero]))
        )
    else:
        p90_ape = 0.0
        p95_ape = 0.0
        over_forecast_rate = 0.0
        over_forecast_ratio = 0.0

    # Business-leaning asymmetric penalty: over-forecast is slightly more expensive.
    asym_cost = (
        np.maximum(pred - actual, 0.0) * 1.2
        + np.maximum(actual - pred, 0.0) * 1.0
    )
    asym_loss = float(np.mean(asym_cost) / max(scale, 1.0))
    quality_score = (
        0.35 * mae_scaled
        + 0.15 * over_bias
        + 0.15 * zero_mismatch
        + 0.10 * volatility_gap
        + 0.15 * asym_loss
        + 0.05 * p90_ape
        + 0.05 * p95_ape
    )
    return {
        "quality_score": float(quality_score),
        "mae_scaled": float(mae_scaled),
        "over_bias": float(over_bias),
        "zero_mismatch": float(zero_mismatch),
        "volatility_gap": float(volatility_gap),
        "asym_loss": float(asym_loss),
        "p90_ape": float(p90_ape),
        "p95_ape": float(p95_ape),
        "over_forecast_rate": float(over_forecast_rate),
        "over_forecast_ratio": float(over_forecast_ratio),
    }


def _model_effective_score(model):
    wmape = float(model.get("wmape", MAX_WMAPE_CAP))
    quality = float(model.get("quality_score", wmape))
    diagnostics = model.get("diagnostics") or {}
    p95_ape = float(diagnostics.get("p95_ape", 0.0))
    over_forecast_ratio = float(diagnostics.get("over_forecast_ratio", 0.0))
    if not np.isfinite(wmape):
        wmape = MAX_WMAPE_CAP
    if not np.isfinite(quality):
        quality = wmape
    if not np.isfinite(p95_ape):
        p95_ape = 0.0
    if not np.isfinite(over_forecast_ratio):
        over_forecast_ratio = 0.0
    risk_penalty = 0.10 * p95_ape + 0.08 * over_forecast_ratio
    return float(0.68 * wmape + 0.22 * quality + risk_penalty)


def _ensemble_guardrail_reasons(candidate, best_component):
    candidate_diag = candidate.get("diagnostics") or {}
    best_diag = best_component.get("diagnostics") or {}
    candidate_wmape = float(candidate.get("wmape", MAX_WMAPE_CAP))
    best_wmape = float(best_component.get("wmape", MAX_WMAPE_CAP))
    candidate_p95 = float(candidate_diag.get("p95_ape", 0.0))
    best_p95 = float(best_diag.get("p95_ape", 0.0))
    candidate_over = float(candidate_diag.get("over_forecast_ratio", 0.0))
    best_over = float(best_diag.get("over_forecast_ratio", 0.0))

    reasons = []
    if np.isfinite(best_wmape) and np.isfinite(candidate_wmape):
        if candidate_wmape > best_wmape + ENSEMBLE_GUARDRAIL_WMAPE_DELTA:
            reasons.append(
                f"wmape {candidate_wmape:.2%} > {best_wmape:.2%} + {ENSEMBLE_GUARDRAIL_WMAPE_DELTA:.2%}"
            )
    if np.isfinite(best_p95) and np.isfinite(candidate_p95):
        p95_limit = best_p95 * ENSEMBLE_GUARDRAIL_P95_FACTOR + ENSEMBLE_GUARDRAIL_P95_DELTA
        if candidate_p95 > p95_limit:
            reasons.append(
                f"p95_ape {candidate_p95:.2%} > {p95_limit:.2%}"
            )
    if np.isfinite(best_over) and np.isfinite(candidate_over):
        over_limit = best_over + ENSEMBLE_GUARDRAIL_OVER_RATIO_DELTA
        if candidate_over > over_limit:
            reasons.append(
                f"over_ratio {candidate_over:.2%} > {over_limit:.2%}"
            )
    return reasons


def _get_model_diagnostics(model):
    diagnostics = model.get("diagnostics") or {}
    wmape = float(model.get("wmape", MAX_WMAPE_CAP))
    p95_ape = float(diagnostics.get("p95_ape", 0.0))
    over_forecast_ratio = float(diagnostics.get("over_forecast_ratio", 0.0))
    if not np.isfinite(wmape):
        wmape = MAX_WMAPE_CAP
    if not np.isfinite(p95_ape):
        p95_ape = 0.0
    if not np.isfinite(over_forecast_ratio):
        over_forecast_ratio = 0.0
    return {
        "wmape": wmape,
        "p95_ape": p95_ape,
        "over_forecast_ratio": over_forecast_ratio,
    }


def _filter_fusion_pool_outliers(models):
    """
    Keep fusion diversity but remove clearly dominated models that tend to
    amplify tail error and over-forecast risk.
    """
    if len(models) <= 2:
        return models
    wmape_arr = []
    p95_arr = []
    over_arr = []
    for m in models:
        diag = _get_model_diagnostics(m)
        wmape_arr.append(diag["wmape"])
        p95_arr.append(diag["p95_ape"])
        over_arr.append(diag["over_forecast_ratio"])
    wmape_med = float(np.median(wmape_arr))
    p95_med = float(np.median(p95_arr))
    over_med = float(np.median(over_arr))
    kept = []
    for m in models:
        diag = _get_model_diagnostics(m)
        wmape_bad = diag["wmape"] > max(wmape_med * 1.25, wmape_med + 0.02)
        p95_bad = diag["p95_ape"] > max(p95_med * 1.35, p95_med + 0.10)
        over_bad = diag["over_forecast_ratio"] > max(over_med * 1.35, over_med + 0.04)
        # Drop only when multi-dimensional risk is jointly bad.
        if (wmape_bad and p95_bad) or (wmape_bad and over_bad):
            continue
        kept.append(m)
    return kept if len(kept) >= 2 else models


def _compute_diversity_boost(model_preds, test_series):
    if len(model_preds) <= 1:
        return [1.0] * len(model_preds)
    scale = _safe_nonzero_mean(test_series)
    boosts = []
    for i, preds in enumerate(model_preds):
        distances = []
        for j, other in enumerate(model_preds):
            if i == j:
                continue
            m = min(len(preds), len(other))
            if m == 0:
                continue
            distances.append(float(np.mean(np.abs(np.asarray(preds[:m]) - np.asarray(other[:m])))))
        avg_distance = float(np.mean(distances)) if distances else 0.0
        # Encourage diversity but cap effect to avoid instability.
        boost = 1.0 + min(avg_distance / max(scale, 1.0), 0.2)
        boosts.append(boost)
    return boosts


def _infer_fusion_regime(screening, train, test, conservative):
    zero_ratio = float((screening or {}).get("zero_ratio", 0.0))
    recent_ratio = float((screening or {}).get("recent_to_prior_ratio", 1.0))
    validation_non_zero = int(np.count_nonzero(np.asarray(test, dtype=float) > 0))
    history_weeks = int(len(train))
    if conservative or validation_non_zero <= 3 or zero_ratio >= 0.6:
        return "sparse"
    if recent_ratio <= 0.45:
        return "collapse"
    if history_weeks >= 104 and zero_ratio <= 0.35 and recent_ratio >= 0.85:
        return "stable"
    return "mixed"


def _allow_tree_models_in_conservative(screening, train, test):
    screening = screening or {}
    recommendation = str(screening.get("recommendation", "")).lower()
    is_anomalous = bool(screening.get("is_anomalous", False))
    zero_ratio = float(screening.get("zero_ratio", 1.0))
    recent_to_prior_ratio = float(screening.get("recent_to_prior_ratio", 0.0))
    validation_non_zero = int(np.count_nonzero(np.asarray(test, dtype=float) > 0))
    history_weeks = int(len(train))
    # Keep conservative stance, but allow trees to participate when signal
    # is not extremely sparse/collapsed.
    return (
        recommendation != "zero_override"
        and not is_anomalous
        and
        history_weeks >= 104
        and validation_non_zero >= 5
        and zero_ratio <= 0.70
        and recent_to_prior_ratio >= 0.18
    )


def _fusion_model_gate_factor(model_name, regime):
    name = str(model_name)
    robust = {"ZeroAwareNaive", "LowSignalMedian", "CrostonSBA", "SeasonalNaive"}
    tree = {"XGBoost", "LightGBM"}
    if regime == "sparse":
        if name in robust:
            return 1.25
        if name in tree or name == "Prophet":
            return 0.8
        return 1.0
    if regime == "collapse":
        if name in robust:
            return 1.2
        if name == "AutoARIMA":
            return 1.1
        return 0.95
    if regime == "stable":
        if name in tree or name in {"Prophet", "AutoARIMA"}:
            return 1.15
        if name in robust:
            return 0.9
        return 1.0
    # mixed
    if name in robust:
        return 1.05
    if name in tree:
        return 1.05
    return 1.0


def _build_horizon_weight_matrix(component_names, base_weights, n_steps, regime):
    weights = np.asarray(base_weights, dtype=float).copy()
    if weights.size == 0:
        return np.zeros((0, n_steps), dtype=float)
    if np.sum(weights) <= 0:
        weights[:] = 1.0 / len(weights)
    else:
        weights = weights / np.sum(weights)

    robust = {"ZeroAwareNaive", "LowSignalMedian", "CrostonSBA", "SeasonalNaive"}
    matrix = np.zeros((len(component_names), n_steps), dtype=float)
    for h in range(n_steps):
        # split by horizon: near(0-3), mid(4-7), far(8+)
        if h <= 3:
            horizon_phase = "near"
        elif h <= 7:
            horizon_phase = "mid"
        else:
            horizon_phase = "far"

        row = weights.copy()
        for i, name in enumerate(component_names):
            is_robust = name in robust
            if regime == "sparse":
                if horizon_phase == "near":
                    row[i] *= 1.25 if is_robust else 0.85
                elif horizon_phase == "mid":
                    row[i] *= 1.15 if is_robust else 0.9
                else:
                    row[i] *= 1.05 if is_robust else 0.95
            elif regime == "stable":
                if horizon_phase == "near":
                    row[i] *= 0.95 if is_robust else 1.1
                elif horizon_phase == "mid":
                    row[i] *= 0.9 if is_robust else 1.12
                else:
                    row[i] *= 0.95 if is_robust else 1.05
            elif regime == "collapse":
                if horizon_phase == "near":
                    row[i] *= 1.2 if is_robust else 0.9
                elif horizon_phase == "mid":
                    row[i] *= 1.1 if is_robust else 0.95
                else:
                    row[i] *= 1.0
            else:
                if horizon_phase == "mid":
                    row[i] *= 1.05

        s = float(np.sum(row))
        if s <= 0:
            row[:] = 1.0 / len(row)
        else:
            row = row / s
        matrix[:, h] = row
    # Smooth horizon weights to reduce step-wise jitter on long-horizon forecasts.
    if matrix.size > 0:
        smooth_alpha = 0.30 if regime == "sparse" else 0.22 if regime == "mixed" else 0.15
        for h in range(1, matrix.shape[1]):
            matrix[:, h] = (1.0 - smooth_alpha) * matrix[:, h] + smooth_alpha * matrix[:, h - 1]
            s = float(np.sum(matrix[:, h]))
            matrix[:, h] = matrix[:, h] / s if s > 0 else np.full(matrix.shape[0], 1.0 / matrix.shape[0], dtype=float)
    return matrix


def _project_to_simplex(weights: np.ndarray) -> np.ndarray:
    """Project arbitrary vector to probability simplex (w>=0, sum(w)=1)."""
    v = np.asarray(weights, dtype=float).flatten()
    if v.size == 0:
        return v
    if np.all(np.isfinite(v)) and np.all(v >= 0.0) and abs(float(np.sum(v)) - 1.0) <= 1e-8:
        return v
    v = np.where(np.isfinite(v), v, 0.0)
    u = np.sort(v)[::-1]
    cssv = np.cumsum(u)
    rho_candidates = np.where(u - (cssv - 1.0) / (np.arange(len(u)) + 1) > 0)[0]
    if len(rho_candidates) == 0:
        return np.full_like(v, 1.0 / len(v), dtype=float)
    rho = int(rho_candidates[-1])
    theta = float((cssv[rho] - 1.0) / (rho + 1))
    w = np.maximum(v - theta, 0.0)
    s = float(np.sum(w))
    if s <= 0:
        return np.full_like(v, 1.0 / len(v), dtype=float)
    return w / s


def _optimize_fusion_weights(
    pred_matrix: np.ndarray,
    actual: np.ndarray,
    init_weights: list[float],
    regime: str,
) -> np.ndarray:
    """Simplex-constrained optimization for weighted fusion.

    Objective (smooth approximation):
    - fit term: MSE on validation window
    - directional risk term: over-forecast penalty
    - stability term: L2 distance to prior (init_weights)
    """
    p = np.asarray(pred_matrix, dtype=float)
    if not np.all(np.isfinite(p)):
        p = np.where(np.isfinite(p), p, 0.0)
    y = np.asarray(actual, dtype=float).flatten()
    if p.ndim != 2 or p.shape[0] == 0 or p.shape[1] == 0:
        return np.asarray(init_weights, dtype=float)
    n_models, horizon = p.shape
    if y.size != horizon:
        if y.size > horizon:
            y = y[:horizon]
        elif y.size == 0:
            y = np.zeros(horizon, dtype=float)
        else:
            y = np.pad(y, (0, horizon - y.size), mode="edge")

    prior = _project_to_simplex(np.asarray(init_weights, dtype=float))
    if prior.size != n_models:
        prior = np.full(n_models, 1.0 / n_models, dtype=float)
    w = prior.copy()

    if regime == "sparse":
        over_penalty, l2_penalty, lr, steps = 0.20, 0.12, 0.15, 80
    elif regime == "collapse":
        over_penalty, l2_penalty, lr, steps = 0.16, 0.10, 0.18, 90
    elif regime == "stable":
        over_penalty, l2_penalty, lr, steps = 0.10, 0.06, 0.22, 100
    else:
        over_penalty, l2_penalty, lr, steps = 0.12, 0.08, 0.20, 90

    scale = max(float(np.mean(np.abs(y))) if y.size > 0 else 1.0, 1.0)
    prev_obj = float("inf")
    for _ in range(steps):
        yhat = np.dot(w, p)
        err = yhat - y
        grad_fit = (2.0 / max(horizon, 1)) * np.dot(p, err) / (scale * scale)
        over_mask = (err > 0).astype(float)
        grad_over = (over_penalty / max(horizon, 1)) * np.dot(p, over_mask) / scale
        grad_reg = 2.0 * l2_penalty * (w - prior)
        obj = (
            float(np.mean(np.square(err)) / (scale * scale))
            + over_penalty * float(np.mean(np.maximum(err, 0.0)) / scale)
            + l2_penalty * float(np.sum(np.square(w - prior)))
        )
        w = _project_to_simplex(w - lr * (grad_fit + grad_over + grad_reg))
        if abs(prev_obj - obj) <= 1e-6:
            break
        prev_obj = obj
    return w


def _blend_with_prior_weights(prior: np.ndarray, optimized: np.ndarray, regime: str) -> np.ndarray:
    prior = _project_to_simplex(np.asarray(prior, dtype=float))
    optimized = _project_to_simplex(np.asarray(optimized, dtype=float))
    if prior.size == 0 or optimized.size == 0 or prior.size != optimized.size:
        return optimized
    # Keep stronger inertia on sparse/collapse regimes.
    mix = 0.58 if regime == "sparse" else 0.50 if regime == "collapse" else 0.40 if regime == "mixed" else 0.32
    blended = mix * prior + (1.0 - mix) * optimized
    return _project_to_simplex(blended)


def run_prophet(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    global _PROPHET_LAST_FAILURE_REASON
    if Prophet is None:
        _PROPHET_LAST_FAILURE_REASON = "prophet_not_installed"
        if verbose:
            _emit_model_log(None, "Prophet skipped: package not installed")
        return None
    try:
        regime = _infer_model_regime(train, screening)
        df_train = pd.DataFrame({'ds': train.index, 'y': train.values})

        if df_train.empty:
            if verbose:
                _emit_model_log(None, "Prophet failed: empty training data")
            else:
                _emit_model_log(None, "Prophet failed: empty training data")
            return None

        if train_exog is not None:
            if not train_exog.empty:
                train_exog_aligned = train_exog.reindex(train.index)
                for col in train_exog_aligned.columns:
                    if not train_exog_aligned[col].isna().all():
                        df_train[col] = train_exog_aligned[col].values
        seasonality_mode = 'multiplicative' if regime["history_weeks"] >= 26 and regime["zero_ratio"] < 0.5 else 'additive'
        changepoint_prior_scale = 0.05 if regime["stable"] else 0.12
        seasonality_prior_scale = 5.0 if regime["history_weeks"] >= 104 else 10.0
        changepoint_range = 0.9 if regime["history_weeks"] >= 52 else 0.8
        model = Prophet(
            seasonality_mode=seasonality_mode,
            changepoint_prior_scale=changepoint_prior_scale,
            seasonality_prior_scale=seasonality_prior_scale,
            changepoint_range=changepoint_range,
            weekly_seasonality=False,
            yearly_seasonality=False,
        )
        if regime["history_weeks"] >= 13:
            model.add_seasonality(name='13w', period=13, fourier_order=3)
        if regime["history_weeks"] >= 52:
            model.add_seasonality(name='52w', period=52, fourier_order=5)
        if train_exog is not None:
            if not train_exog.empty:
                for col in train_exog.columns:
                    model.add_regressor(col)
        model.fit(df_train)
        df_test = pd.DataFrame({'ds': test.index})
        if test_exog is not None:
            if not test_exog.empty:
                test_exog_aligned = test_exog.reindex(test.index)
                for col in test_exog_aligned.columns:
                    if not test_exog_aligned[col].isna().all():
                        df_test[col] = test_exog_aligned[col].values
        forecast = model.predict(df_test)
        y_pred = forecast['yhat'].values
        y_pred = np.maximum(y_pred, 0)
        if regime["zero_heavy"]:
            y_pred = np.minimum(y_pred, max(regime["recent_mean"] * 1.2, 1.0))
        wmape = calculate_wmape(test.values, y_pred, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, y_pred)
        return {
            'name': 'Prophet',
            'wmape': wmape,
            'quality_score': quality["quality_score"],
            'diagnostics': quality,
            'preds': y_pred,
            'model': model,
            'params': model.params if hasattr(model, 'params') else {}
        }
    except Exception as e:
        _PROPHET_LAST_FAILURE_REASON = str(e)
        if verbose:
            _emit_model_log(None, f"Prophet failed: {e}")
            import traceback
            traceback.print_exc()
        return None


def run_xgboost(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        regime = _infer_model_regime(train, screening)
        fe = FeatureEngineer()
        X_train, y_train = fe.make_features(pd.DataFrame(train), train_exog)
        fallback_without_exog = False
        if X_train.empty or y_train.empty:
            # Fallback: exogenous features may collapse rows after lag/rolling.
            # Retry with pure history features to keep tree model in competition.
            X_train, y_train = fe.make_features(pd.DataFrame(train), None)
            fallback_without_exog = True
            if X_train.empty or y_train.empty:
                _emit_model_log(None, "XGBoost failed: empty training data")
                return None

        X_test, _ = fe.make_features_for_prediction(pd.DataFrame(test), None if fallback_without_exog else test_exog)
        train_cv = float(np.std(train.values) / max(np.mean(np.abs(train.values)), 1.0))
        history = int(regime["history_weeks"])
        params = {
            "n_estimators": 260 if history < 80 else 340,
            "max_depth": 4 if train_cv < 1.1 else 5,
            "learning_rate": 0.06 if history < 80 else 0.045,
            "subsample": 0.88 if train_cv < 1.0 else 0.82,
            "colsample_bytree": 0.82,
            "min_child_weight": 4 if history >= 80 else 3,
            "reg_alpha": 0.08 if train_cv < 1.0 else 0.12,
            "reg_lambda": 1.1,
            "objective": "reg:squarederror",
            "random_state": 42,
            "n_jobs": -1,
            "verbosity": 0,
        }
        if regime["zero_heavy"]:
            params.update({"max_depth": 3, "min_child_weight": 7, "learning_rate": 0.03, "subsample": 0.8})
        model = XGBRegressor(**params)
        eval_set = None
        fit_kwargs = {"verbose": False}
        def _fit_xgb(x_fit, y_fit, kwargs):
            try:
                model.fit(x_fit, y_fit, **kwargs)
                return
            except TypeError:
                pass
            # Backward compatibility for older xgboost sklearn wrappers.
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("early_stopping_rounds", None)
            try:
                model.fit(x_fit, y_fit, **retry_kwargs)
                return
            except TypeError:
                pass
            model.fit(x_fit, y_fit)
        if len(X_train) >= 20:
            split = max(4, int(len(X_train) * 0.2))
            if len(X_train) - split >= 12:
                X_fit, X_valid = X_train.iloc[:-split], X_train.iloc[-split:]
                y_fit, y_valid = y_train.iloc[:-split], y_train.iloc[-split:]
                eval_set = [(X_valid, y_valid)]
                fit_kwargs.update({"eval_set": eval_set, "early_stopping_rounds": 25})
                _fit_xgb(X_fit, y_fit, fit_kwargs)
            else:
                _fit_xgb(X_train, y_train, fit_kwargs)
        else:
            _fit_xgb(X_train, y_train, fit_kwargs)
        y_pred = model.predict(X_test)
        y_pred = np.maximum(y_pred, 0)
        if regime["zero_heavy"]:
            y_pred = np.minimum(y_pred, max(regime["recent_mean"] * 1.5, 1.0))
        wmape = calculate_wmape(test.values, y_pred, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, y_pred)
        return {
            'name': 'XGBoost',
            'wmape': wmape,
            'quality_score': quality["quality_score"],
            'diagnostics': quality,
            'preds': y_pred,
            'model': model,
            'params': model.get_params()
        }
    except Exception as e:
        if verbose:
            _emit_model_log(None, f"XGBoost failed: {e}")
            import traceback
            traceback.print_exc()
        else:
            _emit_model_log(None, f"XGBoost failed: {e}")
        return None


def run_lightgbm(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        regime = _infer_model_regime(train, screening)
        fe = FeatureEngineer()
        X_train, y_train = fe.make_features(pd.DataFrame(train), train_exog)
        fallback_without_exog = False
        if X_train.empty or y_train.empty:
            X_train, y_train = fe.make_features(pd.DataFrame(train), None)
            fallback_without_exog = True
            if X_train.empty or y_train.empty:
                _emit_model_log(None, "LightGBM failed: empty training data")
                return None

        X_test, _ = fe.make_features_for_prediction(pd.DataFrame(test), None if fallback_without_exog else test_exog)
        train_cv = float(np.std(train.values) / max(np.mean(np.abs(train.values)), 1.0))
        history = int(regime["history_weeks"])
        params = {
            "n_estimators": 280 if history < 80 else 360,
            "max_depth": -1,
            "num_leaves": 31 if train_cv < 1.2 else 39,
            "learning_rate": 0.055 if history < 80 else 0.04,
            "subsample": 0.88 if train_cv < 1.0 else 0.82,
            "colsample_bytree": 0.82,
            "min_child_samples": 10 if history >= 80 else 8,
            "reg_alpha": 0.08 if train_cv < 1.0 else 0.12,
            "reg_lambda": 1.0,
            "random_state": 42,
            "n_jobs": -1,
            "verbosity": -1,
        }
        if regime["zero_heavy"]:
            params.update({"num_leaves": 15, "learning_rate": 0.03, "min_child_samples": 16, "subsample": 0.8})
        model = LGBMRegressor(**params)
        fit_kwargs = {"verbose": -1}
        def _fit_lgb(x_fit, y_fit, kwargs):
            try:
                model.fit(x_fit, y_fit, **kwargs)
                return
            except TypeError:
                pass
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("verbose", None)
            try:
                model.fit(x_fit, y_fit, **retry_kwargs)
                return
            except TypeError:
                pass
            model.fit(x_fit, y_fit)
        if len(X_train) >= 20:
            split = max(4, int(len(X_train) * 0.2))
            if len(X_train) - split >= 12:
                X_fit, X_valid = X_train.iloc[:-split], X_train.iloc[-split:]
                y_fit, y_valid = y_train.iloc[:-split], y_train.iloc[-split:]
                fit_kwargs.update({"eval_set": [(X_valid, y_valid)]})
                _fit_lgb(X_fit, y_fit, fit_kwargs)
            else:
                _fit_lgb(X_train, y_train, fit_kwargs)
        else:
            _fit_lgb(X_train, y_train, fit_kwargs)
        y_pred = model.predict(X_test)
        y_pred = np.maximum(y_pred, 0)
        if regime["zero_heavy"]:
            y_pred = np.minimum(y_pred, max(regime["recent_mean"] * 1.5, 1.0))
        wmape = calculate_wmape(test.values, y_pred, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, y_pred)
        return {
            'name': 'LightGBM',
            'wmape': wmape,
            'quality_score': quality["quality_score"],
            'diagnostics': quality,
            'preds': y_pred,
            'model': model,
            'params': model.get_params()
        }
    except Exception as e:
        if verbose:
            _emit_model_log(None, f"LightGBM failed: {e}")
            import traceback
            traceback.print_exc()
        else:
            _emit_model_log(None, f"LightGBM failed: {e}")
        return None


def run_auto_arima(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        regime = _infer_model_regime(train, screening)
        exog = train_exog.values if train_exog is not None else None
        seasonal = regime["history_weeks"] >= 52 and not regime["zero_heavy"]
        if regime["history_weeks"] >= 104:
            m = 52
        elif regime["history_weeks"] >= 26:
            m = 13
        else:
            m = 1
        model = pm.auto_arima(
            train.values,
            exogenous=exog,
            seasonal=seasonal and m > 1,
            m=m,
            start_p=0,
            start_q=0,
            max_p=3 if regime["history_weeks"] < 104 else 5,
            max_q=3 if regime["history_weeks"] < 104 else 5,
            max_P=1 if m <= 13 else 2,
            max_Q=1 if m <= 13 else 2,
            trace=False,
            error_action='ignore',
            suppress_warnings=True,
            stepwise=True
        )
        test_exog_vals = test_exog.values if test_exog is not None else None
        y_pred = model.predict(n_periods=len(test), exogenous=test_exog_vals, return_conf_int=False)
        y_pred = np.maximum(y_pred, 0)
        if regime["zero_heavy"]:
            y_pred = np.minimum(y_pred, max(regime["recent_mean"] * 1.2, 1.0))
        wmape = calculate_wmape(test.values, y_pred, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, y_pred)
        return {
            'name': 'AutoARIMA',
            'wmape': wmape,
            'quality_score': quality["quality_score"],
            'diagnostics': quality,
            'preds': y_pred,
            'model': model,
            'params': model.get_params()
        }
    except Exception as e:
        if verbose:
            _emit_model_log(None, f"AutoARIMA failed: {e}")
        else:
            _emit_model_log(None, f"AutoARIMA failed: {e}")
        return None


def _emit_model_log(log_fn, message):
    try:
        safe_message = str(message)
    except Exception:
        safe_message = repr(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_message = safe_message.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
    if log_fn is not None:
        log_fn(safe_message)
    else:
        print(safe_message)

def run_seasonal_naive(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        clean = _series_to_float_series(train)
        if clean.empty:
            return None

        regime = _infer_model_regime(clean, screening)
        if regime["history_weeks"] >= 52:
            season_length = 52
        elif regime["history_weeks"] >= 26:
            season_length = 13
        else:
            season_length = max(4, min(8, regime["history_weeks"]))

        if season_length <= 1:
            forecast = np.full(len(test), float(clean.mean()) if len(clean) > 0 else 0.0)
        elif len(clean) >= season_length:
            tail = clean.iloc[-season_length:].to_numpy()
            forecast = np.resize(tail, len(test))
        else:
            forecast = np.full(len(test), float(clean.mean()) if len(clean) > 0 else 0.0)

        if regime["zero_heavy"]:
            forecast = np.minimum(forecast, max(regime["recent_mean"] * 1.3, 1.0))

        forecast = np.maximum(forecast, 0)
        wmape = calculate_wmape(test.values, forecast, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, forecast)
        return {
            "name": "SeasonalNaive",
            "wmape": wmape,
            "quality_score": quality["quality_score"],
            "diagnostics": quality,
            "preds": forecast,
            "model": None,
            "params": {"season_length": season_length},
        }
    except Exception as e:
        if verbose:
            print(f"SeasonalNaive 澶辫触: {e}")
        return None


def run_zero_aware_naive(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        forecast = _build_zero_aware_forecast(train, len(test), screening)
        wmape = calculate_wmape(test.values, forecast, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, forecast)
        return {
            "name": "ZeroAwareNaive",
            "wmape": wmape,
            "quality_score": quality["quality_score"],
            "diagnostics": quality,
            "preds": forecast,
            "model": None,
            "params": {"strategy": "zero_aware"},
        }
    except Exception as e:
        if verbose:
            print(f"ZeroAwareNaive 澶辫触: {e}")
        return None


def _croston_sba_forecast(train_series, n_steps, alpha=0.15):
    values = np.asarray(train_series, dtype=float)
    values = np.maximum(values, 0.0)
    if values.size == 0:
        return np.zeros(n_steps)

    non_zero_idx = np.where(values > 0)[0]
    if non_zero_idx.size == 0:
        return np.zeros(n_steps)

    first_idx = int(non_zero_idx[0])
    z = float(values[first_idx])
    p = 1.0
    interval = 1

    for x in values[first_idx + 1 :]:
        if x > 0:
            z = z + alpha * (float(x) - z)
            p = p + alpha * (interval - p)
            interval = 1
        else:
            interval += 1

    demand_rate = z / p if p > 0 else 0.0
    sba_rate = max((1.0 - alpha / 2.0) * demand_rate, 0.0)
    return np.full(n_steps, sba_rate, dtype=float)


def run_croston_sba(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        clean = _series_to_float_series(train)
        if clean.empty:
            return None
        regime = _infer_model_regime(clean, screening)
        forecast = _croston_sba_forecast(clean.values, len(test), alpha=0.15)
        if regime["zero_heavy"]:
            cap = max(regime["recent_mean"] * 1.2, 1.0)
            forecast = np.minimum(forecast, cap)
        forecast = np.maximum(forecast, 0)
        wmape = calculate_wmape(test.values, forecast, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, forecast)
        return {
            "name": "CrostonSBA",
            "wmape": wmape,
            "quality_score": quality["quality_score"],
            "diagnostics": quality,
            "preds": forecast,
            "model": None,
            "params": {"alpha": 0.15, "variant": "SBA"},
        }
    except Exception as e:
        if verbose:
            print(f"CrostonSBA 澶辫触: {e}")
        return None


def run_low_signal_median(train, test, train_exog=None, test_exog=None, verbose=False, screening=None):
    try:
        clean = _series_to_float_series(train)
        if clean.empty:
            return None

        recent = clean.tail(min(16, len(clean)))
        recent_non_zero = recent[recent > 0]
        zero_ratio = float((recent == 0).mean()) if len(recent) > 0 else 1.0
        anchor = float(recent_non_zero.median()) if not recent_non_zero.empty else float(recent.mean())
        anchor = max(anchor, 0.0)
        if anchor == 0.0:
            forecast = np.zeros(len(test))
        else:
            if zero_ratio <= 0.25:
                forecast = np.full(len(test), anchor, dtype=float)
            elif zero_ratio <= 0.5:
                decay = np.linspace(1.0, 0.65, len(test))
                forecast = anchor * decay
            else:
                decay = np.linspace(1.0, 0.35, len(test))
                forecast = anchor * decay

        if screening is not None and float(screening.get("recent_mean", 0.0)) > 0:
            cap = max(float(screening.get("recent_mean", 0.0)) * 1.4, 1.0)
            forecast = np.minimum(forecast, cap)

        forecast = np.maximum(forecast, 0.0)
        wmape = calculate_wmape(test.values, forecast, min_non_zero_points=4)
        quality = _compute_prediction_quality(test.values, forecast)
        return {
            "name": "LowSignalMedian",
            "wmape": wmape,
            "quality_score": quality["quality_score"],
            "diagnostics": quality,
            "preds": forecast,
            "model": None,
            "params": {"strategy": "recent_median", "recent_window": int(len(recent))},
        }
    except Exception as e:
        if verbose:
            print(f"LowSignalMedian 澶辫触: {e}")
        return None


def run_all_models(
    train,
    test,
    mode='smart',
    train_exog=None,
    test_exog=None,
    verbose=False,
    log_fn=None,
    screening=None,
    model_policy='standard',
):
    """
    运行所有预测模型，并输出分层结果：
    1) base: 通用算法
    2) robust: 低信号/间歇性需求稳健算法
    3) ensemble: 综合算法（在单模型结果基础上构建）
    """
    models = []
    base_models = []
    robust_models = []
    conservative = str(model_policy).lower() == "conservative"
    allow_trees_under_conservative = _allow_tree_models_in_conservative(screening, train, test)
    screening_obj = screening or {}
    conservative_reason = (
        f"zero_ratio={float(screening_obj.get('zero_ratio', 1.0)):.2f}, "
        f"recent_to_prior_ratio={float(screening_obj.get('recent_to_prior_ratio', 0.0)):.2f}, "
        f"validation_non_zero={int(np.count_nonzero(np.asarray(test, dtype=float) > 0))}, "
        f"history_weeks={len(train)}"
    )
    enabled_base_models = []

    _emit_model_log(log_fn, f"\n模型竞赛启动 (mode={mode})...")
    _emit_model_log(log_fn, f"模型策略: {'conservative' if conservative else 'standard'}")
    _emit_model_log(log_fn, "=" * 70)

    if conservative:
        _emit_model_log(log_fn, f"跳过 Prophet（conservative 策略，{conservative_reason}）")
    else:
        enabled_base_models.append("Prophet")
        global _PROPHET_RUNTIME_FAILURES
        global _PROPHET_LAST_FAILURE_REASON
        global _PROPHET_CIRCUIT_OPEN_UNTIL
        failure_limit = int(max(1, _PROPHET_RUNTIME_FAILURE_LIMIT))
        now_ts = float(time.time())
        if now_ts < _PROPHET_CIRCUIT_OPEN_UNTIL:
            remaining = int(max(0, _PROPHET_CIRCUIT_OPEN_UNTIL - now_ts))
            _emit_model_log(
                log_fn,
                f"Prophet: 熔断跳过（剩余冷却 {remaining}s，累计失败 {_PROPHET_RUNTIME_FAILURES} 次，阈值 {failure_limit}）"
            )
        else:
            if _PROPHET_RUNTIME_FAILURES >= failure_limit:
                _emit_model_log(
                    log_fn,
                    "Prophet: 熔断冷却结束，执行探测重试。"
                )
                _PROPHET_RUNTIME_FAILURES = max(0, failure_limit - 1)
            prophet_ready, prophet_reason = _check_prophet_runtime()
            if not prophet_ready:
                _emit_model_log(log_fn, f"Prophet: 跳过（运行环境不可用: {prophet_reason}）")
            else:
                if str(prophet_reason).startswith("soft_check:"):
                    _emit_model_log(log_fn, f"Prophet: 软检查放行（{prophet_reason}），进入实际训练尝试")
                _emit_model_log(log_fn, "运行 Prophet...")
                _PROPHET_LAST_FAILURE_REASON = ""
                prophet_result = run_prophet(train, test, train_exog, test_exog, verbose, screening=screening)
                if prophet_result:
                    _PROPHET_RUNTIME_FAILURES = 0
                    _PROPHET_CIRCUIT_OPEN_UNTIL = 0.0
                    prophet_result["stage"] = "base"
                    models.append(prophet_result)
                    base_models.append(prophet_result)
                    _emit_model_log(log_fn, f"Prophet: WMAPE={prophet_result['wmape']:.2%}")
                else:
                    _PROPHET_RUNTIME_FAILURES += 1
                    if _PROPHET_RUNTIME_FAILURES >= failure_limit:
                        _PROPHET_CIRCUIT_OPEN_UNTIL = float(time.time()) + float(_PROPHET_CIRCUIT_COOLDOWN_SEC)
                    failure_reason = _PROPHET_LAST_FAILURE_REASON or "unknown_error"
                    _emit_model_log(
                        log_fn,
                        f"Prophet: 失败（reason={failure_reason}，consecutive_failures={_PROPHET_RUNTIME_FAILURES}）"
                    )

    if conservative and not allow_trees_under_conservative:
        _emit_model_log(log_fn, f"跳过 XGBoost（严格 conservative，{conservative_reason}）")
    else:
        if conservative and allow_trees_under_conservative:
            _emit_model_log(log_fn, f"conservative 放宽：允许 XGBoost 参赛（{conservative_reason}）")
        enabled_base_models.append("XGBoost")
        _emit_model_log(log_fn, "运行 XGBoost...")
        xgboost_result = run_xgboost(train, test, train_exog, test_exog, verbose, screening=screening)
        if xgboost_result:
            xgboost_result["stage"] = "base"
            models.append(xgboost_result)
            base_models.append(xgboost_result)
            _emit_model_log(log_fn, f"XGBoost: WMAPE={xgboost_result['wmape']:.2%}")
        else:
            _emit_model_log(log_fn, "XGBoost: 失败")

    if conservative and not allow_trees_under_conservative:
        _emit_model_log(log_fn, f"跳过 LightGBM（严格 conservative，{conservative_reason}）")
    else:
        if conservative and allow_trees_under_conservative:
            _emit_model_log(log_fn, f"conservative 放宽：允许 LightGBM 参赛（{conservative_reason}）")
        enabled_base_models.append("LightGBM")
        _emit_model_log(log_fn, "运行 LightGBM...")
        lightgbm_result = run_lightgbm(train, test, train_exog, test_exog, verbose, screening=screening)
        if lightgbm_result:
            lightgbm_result["stage"] = "base"
            models.append(lightgbm_result)
            base_models.append(lightgbm_result)
            _emit_model_log(log_fn, f"LightGBM: WMAPE={lightgbm_result['wmape']:.2%}")
        else:
            _emit_model_log(log_fn, "LightGBM: 失败")

    enabled_base_models.append("AutoARIMA")
    _emit_model_log(log_fn, "运行 AutoARIMA...")
    autoarima_result = run_auto_arima(train, test, train_exog, test_exog, verbose, screening=screening)
    if autoarima_result:
        autoarima_result["stage"] = "base"
        models.append(autoarima_result)
        base_models.append(autoarima_result)
        _emit_model_log(log_fn, f"AutoARIMA: WMAPE={autoarima_result['wmape']:.2%}")
    else:
        _emit_model_log(log_fn, "AutoARIMA: 失败")

    models = [m for m in models if m is not None]
    base_models = [m for m in base_models if m is not None]

    _emit_model_log(log_fn, f"\n基础模型运行完成: {len(base_models)}/{len(enabled_base_models)} 个成功")

    # Build robust candidates first so fusion can include them.
    zero_naive_result = run_zero_aware_naive(train, test, train_exog, test_exog, verbose, screening=screening)
    if zero_naive_result:
        zero_naive_result["stage"] = "robust"
        models.append(zero_naive_result)
        robust_models.append(zero_naive_result)
        _emit_model_log(log_fn, f"ZeroAwareNaive: WMAPE={zero_naive_result['wmape']:.2%}")

    croston_result = run_croston_sba(train, test, train_exog, test_exog, verbose, screening=screening)
    if croston_result:
        croston_result["stage"] = "robust"
        models.append(croston_result)
        robust_models.append(croston_result)
        _emit_model_log(log_fn, f"CrostonSBA: WMAPE={croston_result['wmape']:.2%}")

    low_signal_result = run_low_signal_median(train, test, train_exog, test_exog, verbose, screening=screening)
    if low_signal_result:
        low_signal_result["stage"] = "robust"
        models.append(low_signal_result)
        robust_models.append(low_signal_result)
        _emit_model_log(log_fn, f"LowSignalMedian: WMAPE={low_signal_result['wmape']:.2%}")

    seasonal_naive_result = run_seasonal_naive(train, test, train_exog, test_exog, verbose, screening=screening)
    if seasonal_naive_result:
        seasonal_naive_result["stage"] = "robust"
        models.append(seasonal_naive_result)
        robust_models.append(seasonal_naive_result)
        _emit_model_log(log_fn, f"SeasonalNaive: WMAPE={seasonal_naive_result['wmape']:.2%}")

    # Fusion pool strategy:
    # - standard: base models + best robust model
    # - conservative: all atomic models (base + robust)
    robust_models = [m for m in robust_models if m is not None]
    fusion_pool = list(base_models)
    if conservative:
        fusion_pool = [m for m in (base_models + robust_models) if m is not None]
    elif robust_models:
        best_robust = min(robust_models, key=_model_effective_score)
        fusion_pool.append(best_robust)

    fusion_pool = _filter_fusion_pool_outliers([m for m in fusion_pool if m is not None])
    if len(fusion_pool) >= 2:
        _emit_model_log(log_fn, "运行融合算法...")
        fusion_regime = _infer_fusion_regime(screening, train, test, conservative)
        _emit_model_log(log_fn, f"融合场景门控: {fusion_regime}")

        avg_components = [m["name"] for m in fusion_pool]
        avg_forecast = np.mean([m["preds"] for m in fusion_pool], axis=0)
        avg_wmape = calculate_wmape(test, avg_forecast, min_non_zero_points=4)
        avg_quality = _compute_prediction_quality(test, avg_forecast)
        models.append(
            {
                "name": "Ensemble-Avg",
                "stage": "ensemble",
                "preds": avg_forecast,
                "wmape": avg_wmape,
                "quality_score": avg_quality["quality_score"],
                "diagnostics": avg_quality,
                "model": None,
                "component_models": avg_components,
                "component_weights": {name: 1.0 / len(avg_components) for name in avg_components},
            }
        )
        _emit_model_log(log_fn, f"Ensemble-Avg: WMAPE={avg_wmape:.2%}")

        effective_scores = [_model_effective_score(m) for m in fusion_pool]
        inv_weights = [1.0 / max(score, 1e-6) if np.isfinite(score) else 0.0 for score in effective_scores]
        gate_factors = [_fusion_model_gate_factor(m["name"], fusion_regime) for m in fusion_pool]
        inv_weights = [inv_weights[i] * gate_factors[i] for i in range(len(inv_weights))]
        weight_sum = float(sum(inv_weights))
        if weight_sum > 0:
            prior_weights = [w / weight_sum for w in inv_weights]
            base_models_for_weighted = list(fusion_pool)
            component_names = [m["name"] for m in base_models_for_weighted]
            pred_matrix = np.vstack([np.asarray(m["preds"], dtype=float) for m in base_models_for_weighted])
            optimized_weights = _optimize_fusion_weights(
                pred_matrix=pred_matrix,
                actual=np.asarray(test.values, dtype=float),
                init_weights=prior_weights,
                regime=fusion_regime,
            )
            optimized_weights = _blend_with_prior_weights(
                prior=np.asarray(prior_weights, dtype=float),
                optimized=np.asarray(optimized_weights, dtype=float),
                regime=fusion_regime,
            )
            diversity_boost = _compute_diversity_boost([m["preds"] for m in fusion_pool], test.values)
            weights = [float(optimized_weights[i]) * float(diversity_boost[i]) for i in range(len(optimized_weights))]
            boost_sum = float(sum(weights))
            weights = [w / boost_sum for w in weights] if boost_sum > 0 else [1.0 / len(fusion_pool)] * len(fusion_pool)
            horizon_weight_matrix = _build_horizon_weight_matrix(component_names, weights, pred_matrix.shape[1], fusion_regime)
            weighted_forecast = np.sum(pred_matrix * horizon_weight_matrix, axis=0)
            weighted_wmape = calculate_wmape(test, weighted_forecast, min_non_zero_points=4)
            weighted_quality = _compute_prediction_quality(test, weighted_forecast)

            # Triple guardrail: fallback when weighted fusion is materially worse
            # on WMAPE / tail error / over-forecast.
            best_component = min(base_models_for_weighted, key=lambda item: float(item.get("wmape", MAX_WMAPE_CAP)))
            best_diag = _get_model_diagnostics(best_component)
            weighted_diag = _get_model_diagnostics(
                {
                    "wmape": weighted_wmape,
                    "diagnostics": weighted_quality,
                }
            )
            guardrail_reasons = _ensemble_guardrail_reasons(
                {
                    "wmape": weighted_diag["wmape"],
                    "diagnostics": {
                        "p95_ape": weighted_diag["p95_ape"],
                        "over_forecast_ratio": weighted_diag["over_forecast_ratio"],
                    },
                },
                {
                    "wmape": best_diag["wmape"],
                    "diagnostics": {
                        "p95_ape": best_diag["p95_ape"],
                        "over_forecast_ratio": best_diag["over_forecast_ratio"],
                    },
                },
            )
            if guardrail_reasons:
                weighted_forecast = np.asarray(best_component["preds"], dtype=float)
                weighted_wmape = calculate_wmape(test, weighted_forecast, min_non_zero_points=4)
                weighted_quality = _compute_prediction_quality(test, weighted_forecast)
                _emit_model_log(
                    log_fn,
                    "Ensemble-Weighted guardrail: fallback to "
                    f"{best_component['name']} (wmape={best_diag['wmape']:.2%}, "
                    f"p95_ape={best_diag['p95_ape']:.2%}, over_ratio={best_diag['over_forecast_ratio']:.2%}, "
                    f"reasons={' | '.join(guardrail_reasons)})",
                )

            component_weights = {
                base_models_for_weighted[idx]["name"]: float(np.mean(horizon_weight_matrix[idx, :]))
                for idx in range(len(base_models_for_weighted))
            }
            models.append(
                {
                    "name": "Ensemble-Weighted",
                    "stage": "ensemble",
                    "preds": weighted_forecast,
                    "wmape": weighted_wmape,
                    "quality_score": weighted_quality["quality_score"],
                    "diagnostics": weighted_quality,
                    "model": None,
                    "component_models": [m["name"] for m in base_models_for_weighted],
                    "component_weights": component_weights,
                    "component_base_weights": {
                        base_models_for_weighted[idx]["name"]: float(weights[idx])
                        for idx in range(len(base_models_for_weighted))
                    },
                    "fusion_regime": fusion_regime,
                    "fusion_segmentation": "near(1-4)/mid(5-8)/far(9-16)",
                }
            )
            _emit_model_log(log_fn, f"Ensemble-Weighted: WMAPE={weighted_wmape:.2%}")

        _emit_model_log(log_fn, "融合算法运行完成")
    else:
        _emit_model_log(log_fn, "基础模型不足 2 个，跳过融合算法")

    # Base results are used by future prediction stage; keep atomic models only.
    atomic_models = [m for m in models if not str(m.get("name", "")).startswith("Ensemble")]
    base_results = {m["name"]: m for m in atomic_models}

    _emit_model_log(log_fn, "=" * 70)

    return models, base_results


def calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates):
    return _get_forecast_kernel().calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates)


def process_single_spu(spu, df_all, mode='smart', exog_cols=None, collect_viz=False, verbose=True, log_fn=None):
    result_df, message, _viz, profile = _get_forecast_kernel().process_single_spu(
        spu,
        df_all,
        mode=mode,
        exog_cols=exog_cols,
        collect_viz=collect_viz,
        verbose=verbose,
        log_fn=log_fn,
    )
    error = None if result_df is not None else message
    return result_df, error, profile


def calculate_spu_accuracy(actual, pred):
    actual_series = pd.Series(actual)
    pred_series = pd.Series(pred).reindex(actual_series.index)
    errors = actual_series - pred_series
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    non_zero = actual_series.replace(0, np.nan)
    mape = float(np.nanmean(np.abs(errors) / non_zero)) if non_zero.notna().any() else 0.0
    return {
        'wmape': float(calculate_wmape(actual_series, pred_series)),
        'mape': 0.0 if np.isnan(mape) else mape,
        'mae': mae,
        'rmse': rmse,
    }


def calculate_sku_accuracy(actual, pred):
    actual_df = pd.DataFrame(actual)
    pred_df = pd.DataFrame(pred).reindex(index=actual_df.index, columns=actual_df.columns, fill_value=0)
    sku_metrics = {}
    total_actual = float(actual_df.to_numpy().sum())
    weighted_error = 0.0

    for sku in actual_df.columns:
        sku_actual = actual_df[sku]
        sku_pred = pred_df[sku]
        wmape = float(calculate_wmape(sku_actual, sku_pred))
        total_sales = float(sku_actual.sum())
        weight = (total_sales / total_actual) if total_actual > 0 else 0.0
        weighted_error += wmape * weight
        sku_metrics[sku] = {
            'wmape': wmape,
            'total_sales': total_sales,
            'weight_in_spu': weight,
        }

    return {
        'wmape': weighted_error,
        'sku_metrics': sku_metrics,
        'sku_accuracy_json': json.dumps(sku_metrics, ensure_ascii=False),
    }


def _predict_prophet_future(series, n_steps, exog_series=None, future_exog=None):
    if Prophet is None:
        clean = _series_to_float_series(series)
        fallback_value = float(clean.tail(8).mean()) if not clean.empty else 0.0
        return np.maximum(np.full(n_steps, fallback_value), 0.0)
    df = pd.DataFrame({"ds": series.index, "y": series.values})
    if exog_series is not None and not exog_series.empty:
        aligned = (
            exog_series.reindex(series.index)
            .astype(float)
            .replace([np.inf, -np.inf], np.nan)
            .ffill()
            .bfill()
            .fillna(0.0)
        )
        for col in aligned.columns:
            df[col] = aligned[col].values
    model = Prophet(
        seasonality_mode="multiplicative",
        changepoint_prior_scale=0.1,
        seasonality_prior_scale=10.0,
        changepoint_range=0.8,
    )
    if exog_series is not None and not exog_series.empty:
        for col in exog_series.columns:
            model.add_regressor(col)
    model.fit(df)
    future = model.make_future_dataframe(periods=n_steps, freq="W")
    if future_exog is not None and not future_exog.empty:
        future_exog_clean = (
            future_exog.copy()
            .astype(float)
            .replace([np.inf, -np.inf], np.nan)
            .ffill()
            .bfill()
            .fillna(0.0)
        )
        if exog_series is not None and not exog_series.empty:
            hist_exog_clean = (
                exog_series.copy()
                .astype(float)
                .replace([np.inf, -np.inf], np.nan)
                .ffill()
                .bfill()
                .fillna(0.0)
            )
        else:
            hist_exog_clean = None
        for col in future_exog_clean.columns:
            if exog_series is not None and not exog_series.empty and col in exog_series.columns:
                hist_exog = hist_exog_clean[col].values
                fut_exog = future_exog_clean[col].values
                all_exog = np.concatenate([hist_exog, fut_exog])
                if len(all_exog) == len(future):
                    future[col] = all_exog
                else:
                    # Prophet regressors cannot contain NaN; use history tail mean as fallback.
                    fallback = float(np.nanmean(hist_exog)) if len(hist_exog) > 0 else 0.0
                    history_part = np.full(len(series), fallback)
                    future[col] = np.concatenate([history_part, fut_exog])
            else:
                fut_exog = future_exog_clean[col].values
                history_part = np.full(len(series), float(np.nanmean(fut_exog)) if len(fut_exog) > 0 else 0.0)
                future[col] = np.concatenate([history_part, fut_exog])
    for col in future.columns:
        if col in ("ds",):
            continue
        future[col] = (
            pd.Series(future[col])
            .astype(float)
            .replace([np.inf, -np.inf], np.nan)
            .ffill()
            .bfill()
            .fillna(0.0)
            .values
        )
    forecast = model.predict(future)
    return np.maximum(forecast["yhat"].values[-n_steps:], 0)


def _predict_tree_future(series, n_steps, winner, exog_series=None, future_exog=None):
    fe = FeatureEngineer()
    X_hist, y_hist = fe.make_features(pd.DataFrame(series), exog_series)
    model = winner.get("model")
    if model is None or X_hist.empty or y_hist.empty:
        clean = _series_to_float_series(series)
        fallback = float(clean.tail(8).mean()) if not clean.empty else 0.0
        return np.maximum(np.full(n_steps, fallback), 0.0)
    model.fit(X_hist, y_hist)
    future_dates = pd.date_range(series.index[-1], periods=n_steps + 1, freq="W")[1:]
    future_df = pd.DataFrame(index=future_dates, columns=["y"])
    future_df["y"] = 0
    if future_exog is not None:
        X_future, _ = fe.make_features_for_prediction(future_df, future_exog)
    else:
        X_future, _ = fe.make_features_for_prediction(future_df)
    preds = model.predict(X_future)
    return np.maximum(preds, 0)


def _predict_auto_arima_future(series, n_steps, exog_series=None, future_exog=None, screening=None):
    clean = _series_to_float_series(series)
    if clean.empty:
        return np.zeros(n_steps)
    regime = _infer_model_regime(clean, screening)
    seasonal = regime["history_weeks"] >= 52 and not regime["zero_heavy"]
    if regime["history_weeks"] >= 104:
        m = 52
    elif regime["history_weeks"] >= 26:
        m = 13
    else:
        m = 1
    model = pm.auto_arima(
        clean.values,
        exogenous=exog_series.values if exog_series is not None else None,
        seasonal=seasonal and m > 1,
        m=m,
        trace=False,
        error_action="ignore",
        suppress_warnings=True,
        stepwise=True,
    )
    preds = model.predict(
        n_periods=n_steps,
        exogenous=future_exog.values if future_exog is not None else None,
        return_conf_int=False,
    )
    return np.maximum(np.asarray(preds, dtype=float), 0.0)


def _predict_seasonal_naive_future(series, n_steps):
    clean = _series_to_float_series(series)
    if clean.empty:
        return np.zeros(n_steps)
    if len(clean) >= 52:
        season_length = 52
    elif len(clean) >= 26:
        season_length = 13
    else:
        season_length = max(4, min(8, len(clean)))
    tail = clean.iloc[-season_length:].to_numpy() if len(clean) >= season_length else np.full(n_steps, float(clean.mean()))
    preds = np.resize(tail, n_steps)
    return np.maximum(preds, 0.0)


def _predict_low_signal_median_future(series, n_steps, screening=None):
    clean = _series_to_float_series(series)
    if clean.empty:
        return np.zeros(n_steps)
    recent = clean.tail(min(16, len(clean)))
    recent_non_zero = recent[recent > 0]
    zero_ratio = float((recent == 0).mean()) if len(recent) > 0 else 1.0
    anchor = float(recent_non_zero.median()) if not recent_non_zero.empty else float(recent.mean())
    anchor = max(anchor, 0.0)
    if anchor == 0.0:
        forecast = np.zeros(n_steps)
    elif zero_ratio <= 0.25:
        forecast = np.full(n_steps, anchor, dtype=float)
    elif zero_ratio <= 0.5:
        forecast = anchor * np.linspace(1.0, 0.65, n_steps)
    else:
        forecast = anchor * np.linspace(1.0, 0.35, n_steps)
    if screening is not None and float(screening.get("recent_mean", 0.0)) > 0:
        cap = max(float(screening.get("recent_mean", 0.0)) * 1.4, 1.0)
        forecast = np.minimum(forecast, cap)
    return np.maximum(forecast, 0.0)


def _predict_ensemble_future(series, winner, n_steps, exog_series=None, future_exog=None, base_results=None, screening=None):
    if not isinstance(base_results, dict):
        base_results = {}
    component_names = [
        name
        for name in winner.get("component_models", [])
        if not str(name).startswith("Ensemble")
    ]
    if not component_names:
        component_names = [name for name in base_results.keys() if not str(name).startswith("Ensemble")]
    component_preds = []
    component_order = []
    for name in component_names:
        candidate = base_results.get(name)
        if candidate is None:
            continue
        preds = _predict_single_model_future(
            series,
            {**candidate, "name": name},
            n_steps,
            exog_series=exog_series,
            future_exog=future_exog,
            base_results=base_results,
            screening=screening,
        )
        if preds is None or len(preds) == 0:
            continue
        component_preds.append(np.asarray(preds, dtype=float))
        component_order.append(name)
    if not component_preds:
        clean = _series_to_float_series(series)
        fallback = float(clean.tail(8).mean()) if not clean.empty else 0.0
        return np.maximum(np.full(n_steps, fallback), 0.0)
    pred_stack = np.vstack(component_preds)
    if winner.get("name") == "Ensemble-Weighted":
        base_weight_map = winner.get("component_base_weights", {}) or winner.get("component_weights", {}) or {}
        weights = np.asarray([float(base_weight_map.get(name, 0.0)) for name in component_order], dtype=float)
        if np.sum(weights) <= 0:
            weights = np.asarray([1.0 / pred_stack.shape[0]] * pred_stack.shape[0], dtype=float)
        else:
            weights = weights / np.sum(weights)
        conservative = str((screening or {}).get("recommendation", "")).lower() != "standard"
        pseudo_test = pd.Series(series).tail(min(max(n_steps, 8), len(series)))
        fusion_regime = str(winner.get("fusion_regime") or _infer_fusion_regime(screening, series, pseudo_test, conservative))
        horizon_weight_matrix = _build_horizon_weight_matrix(component_order, weights, pred_stack.shape[1], fusion_regime)
        merged = np.sum(pred_stack * horizon_weight_matrix, axis=0)
    else:
        merged = np.mean(pred_stack, axis=0)
    return np.maximum(np.asarray(merged, dtype=float), 0.0)


def _predict_single_model_future(series, winner, n_steps, exog_series=None, future_exog=None, base_results=None, screening=None):
    model_name = str(winner.get("name", ""))
    if model_name == "Prophet":
        return _predict_prophet_future(series, n_steps, exog_series=exog_series, future_exog=future_exog)
    if model_name in ["XGBoost", "LightGBM"]:
        return _predict_tree_future(series, n_steps, winner, exog_series=exog_series, future_exog=future_exog)
    if model_name == "AutoARIMA":
        return _predict_auto_arima_future(series, n_steps, exog_series=exog_series, future_exog=future_exog, screening=screening)
    if model_name == "SeasonalNaive":
        return _predict_seasonal_naive_future(series, n_steps)
    if model_name == "ZeroAwareNaive":
        return _build_zero_aware_forecast(series, n_steps, screening)
    if model_name == "CrostonSBA":
        alpha = float((winner.get("params") or {}).get("alpha", 0.15))
        clean = _series_to_float_series(series)
        return _croston_sba_forecast(clean.values, n_steps, alpha=alpha)
    if model_name == "LowSignalMedian":
        return _predict_low_signal_median_future(series, n_steps, screening=screening)
    if model_name in ["Ensemble-Avg", "Ensemble-Weighted"]:
        return _predict_ensemble_future(
            series,
            winner,
            n_steps,
            exog_series=exog_series,
            future_exog=future_exog,
            base_results=base_results,
            screening=screening,
        )
    clean = _series_to_float_series(series)
    fallback = float(clean.tail(8).mean()) if not clean.empty else 0.0
    return np.maximum(np.full(n_steps, fallback), 0.0)


def predict_future(series, winner, n_steps, exog_series=None, future_exog=None, base_results=None, screening=None):
    return _predict_single_model_future(
        series,
        winner,
        n_steps,
        exog_series=exog_series,
        future_exog=future_exog,
        base_results=base_results,
        screening=screening,
    )


def safe_predictions(preds, fallback_value, model_name, history_series=None):
    preds = np.asarray(preds).flatten().copy()
    nan_count = np.sum(np.isnan(preds))
    if nan_count > 0:
        preds[np.isnan(preds)] = fallback_value
    preds = np.maximum(preds, 0)
    if history_series is not None and len(history_series) > 0:
        recent = pd.Series(history_series).tail(12).astype(float)
        recent_non_zero = recent[recent > 0]
        recent_anchor = float(recent_non_zero.median()) if not recent_non_zero.empty else float(fallback_value)
        recent_peak = float(recent.max()) if not recent.empty else float(fallback_value)
        recent_std = float(recent.std(ddof=0)) if len(recent) > 1 else 0.0
        upper_cap = max(
            recent_anchor * 3.0,
            recent_peak * 2.0,
            recent_anchor + recent_std * 3.0,
            float(fallback_value) * 4.0,
            1.0,
        )
        preds = np.minimum(preds, upper_cap)
        if len(preds) > 1 and recent_anchor > 0:
            recent_changes = np.abs(np.diff(recent.to_numpy())) if len(recent) > 1 else np.array([0.0])
            max_step = max(float(np.nanmedian(recent_changes)) * 3.0, recent_std * 2.0, recent_anchor * 0.8, 1.0)
            smoothed = preds.copy()
            for idx in range(1, len(smoothed)):
                if preds[idx] <= 0:
                    smoothed[idx] = 0.0
                    continue
                lower_bound = max(smoothed[idx - 1] - max_step, 0.0)
                upper_bound_step = smoothed[idx - 1] + max_step
                smoothed[idx] = float(np.clip(smoothed[idx], lower_bound, min(upper_cap, upper_bound_step)))
            preds = smoothed
    return preds


def extract_seasonal_factors_52week(series, period=52):
    if Prophet is None:
        factors = {f'week_{i+1}': 1.0 for i in range(period)}
        return json.dumps(factors, ensure_ascii=False)
    try:
        if len(series) < period:
            factors = {f'week_{i+1}': 1.0 for i in range(period)}
            return json.dumps(factors, ensure_ascii=False)
        df = pd.DataFrame({'ds': series.index, 'y': series.values})
        model = Prophet(seasonality_mode='multiplicative', yearly_seasonality=True)
        model.fit(df)
        forecast = model.predict(df)
        seasonal = forecast['yearly'].values
        seasonal = seasonal - seasonal.mean() + 1
        seasonal = np.clip(seasonal, 0.5, 1.5)
        factors = {f'week_{i+1}': float(seasonal[i % period]) for i in range(period)}
        return json.dumps(factors, ensure_ascii=False)
    except Exception as e:
        factors = {f'week_{i+1}': 1.0 for i in range(period)}
        return json.dumps(factors, ensure_ascii=False)


def clean_params_for_db(params):
    if not params:
        return "{}"
    try:
        def clean_value(v):
            if isinstance(v, (np.ndarray, np.generic)):
                return v.tolist()
            elif isinstance(v, (pd.Series, pd.DataFrame)):
                return v.to_dict()
            elif isinstance(v, (list, dict, str, int, float, bool, type(None))):
                return v
            else:
                return str(v)
        clean_params = {k: clean_value(v) for k, v in params.items()}
        return json.dumps(clean_params, ensure_ascii=False)
    except:
        return "{}"


def plot_best_spu_style(profile, train, test, results, future, future_dates, sku_future_df=None, save_path=None, show_plot=True):
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    try:
        font_path = 'static/file-ngwyeoEN29l1M3O1QpdxCwkj-sider-font.ttf'
        if os.path.exists(font_path):
            font_prop = FontProperties(fname=font_path)
            plt.rcParams['font.family'] = font_prop.get_name()
    except:
        pass
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 1]})
    all_dates = pd.date_range(train.index[0], future_dates[-1], freq='W')
    ax1.plot(train.index, train.values, 'gray', label='鍘嗗彶鏁版嵁', linewidth=2)
    ax1.plot(test.index, test.values, 'k-', marker='o', label='Actual', linewidth=2, markersize=6)
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    for i, res in enumerate(results):
        color = colors[i % len(colors)]
        ax1.plot(test.index, res['preds'], color, marker='s', label=f'{res["name"]} (WMAPE: {res["wmape"]:.2%})', linewidth=1.5, markersize=4)
    ax1.plot(future_dates, future, 'purple', marker='d', label=f'{profile.winner_algo} 棰勬祴', linewidth=3, markersize=6)
    if sku_future_df is not None and not sku_future_df.empty:
        top_skus = sku_future_df.sum().nlargest(5).index
        for i, sku in enumerate(top_skus):
            color = colors[(i + 1) % len(colors)]
            ax1.plot(future_dates, sku_future_df[sku], color, linestyle='--', marker='o', label=f'SKU {sku}', linewidth=1.5, markersize=4)
    val_start = test.index[0]
    val_end = test.index[-1]
    ax1.axvspan(val_start, val_end, alpha=0.2, color='yellow', label='楠岃瘉鍖洪棿')
    pred_start = future_dates[0]
    pred_end = future_dates[-1]
    ax1.axvspan(pred_start, pred_end, alpha=0.2, color='green', label='棰勬祴鍖洪棿')
    ax1.set_title(f"SPU {profile.spu} forecast - winner: {profile.winner_algo} (WMAPE: {profile.winner_wmape:.2%})", fontsize=16)
    ax1.set_xlabel("Date", fontsize=12)
    ax1.set_ylabel("Sales", fontsize=12)
    ax1.legend(loc='upper left', fontsize=10, bbox_to_anchor=(1, 1))
    ax1.grid(True, alpha=0.3)
    model_names = [r['name'] for r in results]
    wmapes = [r['wmape'] for r in results]
    winner_idx = model_names.index(profile.winner_algo)
    colors = ['#1f77b4'] * len(model_names)
    colors[winner_idx] = '#d62728'
    ax2.bar(model_names, wmapes, color=colors)
    ax2.set_title("Model WMAPE Comparison", fontsize=14)
    ax2.set_xlabel("Model", fontsize=12)
    ax2.set_ylabel("WMAPE", fontsize=12)
    for i, wmape in enumerate(wmapes):
        ax2.text(i, wmape, f'{wmape:.2%}', ha='center', va='bottom', fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"   馃搳 鍥捐〃宸蹭繚瀛樿嚦: {save_path}")
    if show_plot:
        plt.show()
    plt.close()

