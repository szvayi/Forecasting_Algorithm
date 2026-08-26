"""Canonical forecast execution kernel.

`process_single_spu` lives here now so the runtime can depend on a stable
`src.forecasting` surface instead of importing the legacy root `main.py`.
The legacy root module is still used for `save_to_database` and `main`.
"""

from __future__ import annotations

import datetime
import importlib
import json
import os
import time
from functools import lru_cache
from types import ModuleType

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from src.forecasting.models import SPUProfiler
from src.forecasting.sample_screening import screen_weekly_series
from src.forecasting.predictors import (
    calculate_wmape,
    clean_params_for_db,
    clean_series,
    extract_seasonal_factors_52week,
    get_current_week_end,
    plot_best_spu_style,
    predict_future,
    run_all_models,
    safe_predictions,
)
from src.forecasting.runtime_facade import (
    build_future_exog_frame,
    calculate_dynamic_shares,
    calculate_principal_dynamic_shares,
)

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return int(max(minimum, min(value, maximum)))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return float(max(minimum, min(value, maximum)))


SCOPE_MIN_HISTORY_WEEKS = max(_env_int("SCOPE_MIN_WEEKS", 108), 12)
MAX_TRAIN_HISTORY_WEEKS = max(_env_int("MAX_TRAIN_HISTORY_WEEKS", 156), 12)
VALIDATION_TEST_MIN_WEEKS = max(_env_int("VALIDATION_TEST_MIN_WEEKS", 8), 4)
VALIDATION_TEST_MAX_WEEKS = max(_env_int("VALIDATION_TEST_MAX_WEEKS", 16), VALIDATION_TEST_MIN_WEEKS)
VALIDATION_TEST_DIVISOR = max(_env_int("VALIDATION_TEST_DIVISOR", 4), 2)

CONSERVATIVE_NON_ZERO_MAX = _clamp_int(_env_int("CONSERVATIVE_NON_ZERO_MAX", 4), 1, 16)
CONSERVATIVE_TOTAL_SALES_MIN = max(_env_float("CONSERVATIVE_TOTAL_SALES_MIN", 60.0), 0.0)
CONSERVATIVE_ZERO_RATIO_MIN = _clamp_float(_env_float("CONSERVATIVE_ZERO_RATIO_MIN", 0.70), 0.0, 1.0)
CONSERVATIVE_RECENT_RATIO_MAX = _clamp_float(_env_float("CONSERVATIVE_RECENT_RATIO_MAX", 0.20), 0.0, 1.0)

LOW_SIGNAL_NON_ZERO_MAX = _clamp_int(_env_int("LOW_SIGNAL_NON_ZERO_MAX", 6), 1, 20)
LOW_SIGNAL_TOTAL_SALES_MIN = max(_env_float("LOW_SIGNAL_TOTAL_SALES_MIN", 120.0), 0.0)
LOW_SIGNAL_NON_ZERO_MAX = max(LOW_SIGNAL_NON_ZERO_MAX, CONSERVATIVE_NON_ZERO_MAX)

NEAR_TIE_ENSEMBLE_MARGIN = _clamp_float(_env_float("NEAR_TIE_ENSEMBLE_MARGIN", 0.012), 0.004, 0.03)
DUAL_GUARD_WMAPE_MARGIN_STANDARD = _clamp_float(_env_float("DUAL_GUARD_WMAPE_MARGIN_STANDARD", 0.015), 0.005, 0.03)
DUAL_GUARD_WMAPE_MARGIN_LOW_SIGNAL = _clamp_float(_env_float("DUAL_GUARD_WMAPE_MARGIN_LOW_SIGNAL", 0.02), 0.005, 0.05)
DUAL_GUARD_QUALITY_MARGIN_STANDARD = _clamp_float(_env_float("DUAL_GUARD_QUALITY_MARGIN_STANDARD", 0.05), 0.01, 0.2)
DUAL_GUARD_QUALITY_MARGIN_LOW_SIGNAL = _clamp_float(_env_float("DUAL_GUARD_QUALITY_MARGIN_LOW_SIGNAL", 0.08), 0.02, 0.3)


@lru_cache(maxsize=1)
def _load_legacy_kernel() -> ModuleType:
    return importlib.import_module("main")


def _build_training_data_query() -> str:
    spu_list_env = os.getenv("SPU_LIST", "").strip()
    spu_filter_sql = ""
    if spu_list_env:
        tokens = [s.strip() for s in spu_list_env.split(",") if s.strip()]
        if tokens:
            in_list = ",".join([f"'{t}'" for t in tokens])
            spu_filter_sql = f" and SPU in ({in_list})"

    return f"""
    with base as (
        select
        a."date" as report_date,
        local_sku,
        coalesce(a.principal_names, 'UNKNOWN') as principal_names,
        case
        when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
        when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
        when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
        else '-' end as SPU,
        sum(afn_amount+mfn_amount+promotion_discount+refund_amount+cost_of_points_granted+inventory_credit+shared_fba_liquidation_proceeds+shared_fba_liquidation_proceeds_adjustments
        +shared_amazon_shipping_reimbursement+shared_safe_t_reimbursement+shared_netco_transaction+shared_reimbursements+shared_clawbacks+shared_commingling_vat_income+gift_wrap_credits
        +a_to_z_guarantee_claims+shared_others+shipping_cost) as 销售额,
        sum(a.volume) as 销量,
        avg(avg_net_amount) as 平均售价,
        sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费
        from lx_ods.查询订单利润_msku_cny_5年版 a
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        group by 1,2,3,4
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           max(principal_names) as principal_names,
           ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
    from base
    where 1=1{spu_filter_sql}
    group by report_date, SPU, local_sku
    order by report_date
    """


def get_data_from_db(db_url):
    t0 = time.time()
    query = _build_training_data_query()
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        print("尝试连接数据库...")
        with engine.connect() as conn:
            print("数据库连接成功！")
            print("开始执行SQL查询...")
            df = pd.read_sql(text(query), con=conn)
            print(f"SQL查询执行成功，获取到 {len(df)} 行数据")
        df.columns = [col.lower() for col in df.columns]
        print(f"数据获取完成！共加载 {len(df)} 行记录，耗时: {time.time() - t0:.1f} 秒")
        return df
    except Exception as exc:
        import traceback

        print(f"数据获取失败: {exc}")
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        engine.dispose()
        print("数据库连接已关闭")


def _conservative_model_score(model: dict, test_series: pd.Series) -> float:
    preds = np.asarray(model.get("preds", []), dtype=float).flatten()
    actual = np.asarray(test_series.values, dtype=float).flatten()
    n = min(len(preds), len(actual))
    if n == 0:
        return float("inf")
    preds = np.maximum(preds[:n], 0.0)
    actual = actual[:n]

    wmape = float(model.get("wmape", float("inf")))
    if not np.isfinite(wmape):
        wmape = 9.999

    actual_zero_ratio = float(np.mean(actual == 0.0))
    pred_zero_ratio = float(np.mean(preds <= 1e-6))
    zero_mismatch = abs(pred_zero_ratio - actual_zero_ratio)

    pred_mean = float(np.mean(preds)) if n > 0 else 0.0
    actual_mean = float(np.mean(actual)) if n > 0 else 0.0
    over_bias = max(pred_mean - actual_mean, 0.0) / max(actual_mean, 1.0)

    pred_diff = np.diff(preds) if n > 1 else np.array([0.0])
    pred_jump = float(np.mean(np.abs(pred_diff))) / max(actual_mean, 1.0)

    # Composite score: accuracy first, then consistency and stability.
    return wmape + 0.35 * zero_mismatch + 0.15 * over_bias + 0.10 * pred_jump


def _standard_model_score(model: dict, test_series: pd.Series) -> float:
    """Lightweight tie-breaker for standard policy.

    Keep WMAPE as dominant signal while penalizing over-forecast and unstable
    trajectories when top candidates have similar validation errors.
    """
    preds = np.asarray(model.get("preds", []), dtype=float).flatten()
    actual = np.asarray(test_series.values, dtype=float).flatten()
    n = min(len(preds), len(actual))
    if n == 0:
        return float("inf")
    preds = np.maximum(preds[:n], 0.0)
    actual = actual[:n]

    wmape = float(model.get("wmape", float("inf")))
    if not np.isfinite(wmape):
        wmape = 9.999
    diagnostics = model.get("diagnostics") or {}
    quality_score = float(model.get("quality_score", wmape))
    if not np.isfinite(quality_score):
        quality_score = wmape
    p95_ape = float(diagnostics.get("p95_ape", 0.0))
    over_forecast_ratio = float(diagnostics.get("over_forecast_ratio", 0.0))
    if not np.isfinite(p95_ape):
        p95_ape = 0.0
    if not np.isfinite(over_forecast_ratio):
        over_forecast_ratio = 0.0
    soft_wmape = float(calculate_wmape(actual, preds, min_non_zero_points=1))
    if not np.isfinite(soft_wmape):
        soft_wmape = 9.999

    pred_mean = float(np.mean(preds)) if n > 0 else 0.0
    actual_mean = float(np.mean(actual)) if n > 0 else 0.0
    over_bias = max(pred_mean - actual_mean, 0.0) / max(actual_mean, 1.0)

    pred_diff = np.diff(preds) if n > 1 else np.array([0.0])
    pred_jump = float(np.mean(np.abs(pred_diff))) / max(actual_mean, 1.0)
    pred_zero_ratio = float(np.mean(preds <= 1e-6))
    actual_zero_ratio = float(np.mean(actual == 0.0))
    zero_mismatch = abs(pred_zero_ratio - actual_zero_ratio)

    # In capped-WMAPE scenarios, include soft WMAPE and model diagnostics to
    # improve separation among "same WMAPE" candidates.
    cap_penalty = 0.20 if wmape >= 9.0 else 0.0
    return (
        0.64 * wmape
        + 0.16 * soft_wmape
        + 0.10 * quality_score
        + 0.04 * p95_ape
        + 0.03 * over_forecast_ratio
        + 0.02 * over_bias
        + 0.01 * pred_jump
        + 0.01 * zero_mismatch
        + cap_penalty
    )


def _low_signal_model_score(model: dict, test_series: pd.Series, history_series: pd.Series) -> float:
    """Ranking score for sparse validation windows.

    In low-signal windows, many models hit the capped WMAPE (9.999), so we add
    penalties that favor conservative, non-explosive trajectories.
    """
    preds = np.asarray(model.get("preds", []), dtype=float).flatten()
    actual = np.asarray(test_series.values, dtype=float).flatten()
    n = min(len(preds), len(actual))
    if n == 0:
        return float("inf")
    preds = np.maximum(preds[:n], 0.0)
    actual = actual[:n]

    # Soft WMAPE uses relaxed non-zero requirement, useful for sparse windows.
    soft_wmape = float(calculate_wmape(actual, preds, min_non_zero_points=1))
    if not np.isfinite(soft_wmape):
        soft_wmape = 9.999

    hard_wmape = float(model.get("wmape", 9.999))
    if not np.isfinite(hard_wmape):
        hard_wmape = 9.999

    hist = pd.Series(history_series).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    recent = hist.tail(min(12, len(hist))) if not hist.empty else pd.Series(dtype=float)
    recent_non_zero = recent[recent > 0]
    scale = float(recent_non_zero.median()) if not recent_non_zero.empty else float(recent.mean()) if not recent.empty else 1.0
    scale = max(scale, 1.0)

    mae_all = float(np.mean(np.abs(preds - actual)))
    zero_idx = actual <= 1e-6
    over_on_zero = float(np.mean(preds[zero_idx])) if np.any(zero_idx) else 0.0
    pred_zero_ratio = float(np.mean(preds <= 1e-6))
    actual_zero_ratio = float(np.mean(actual <= 1e-6))
    zero_mismatch = abs(pred_zero_ratio - actual_zero_ratio)

    # Extra penalty when model is in "hard-capped" error regime.
    cap_penalty = 0.35 if hard_wmape >= 9.0 else 0.0
    return (
        0.55 * soft_wmape
        + 0.20 * (mae_all / scale)
        + 0.15 * (over_on_zero / scale)
        + 0.10 * zero_mismatch
        + cap_penalty
    )


def _best_ensemble_candidate(valid_results: list[dict]) -> dict | None:
    ensemble_candidates = [
        candidate
        for candidate in valid_results
        if str(candidate.get("name", "")).startswith("Ensemble")
        and np.isfinite(float(candidate.get("wmape", float("inf"))))
    ]
    if not ensemble_candidates:
        return None
    return min(ensemble_candidates, key=lambda item: float(item.get("wmape", float("inf"))))


def _candidate_stage(candidate: dict) -> str:
    stage = str(candidate.get("stage", "")).strip().lower()
    if stage:
        return stage
    name = str(candidate.get("name", ""))
    if name.startswith("Ensemble"):
        return "ensemble"
    if name in {"ZeroAwareNaive", "CrostonSBA", "LowSignalMedian", "SeasonalNaive"}:
        return "robust"
    return "base"


def _select_stage_best(
    stage_candidates: list[dict],
    test_series: pd.Series,
    history_series: pd.Series,
    model_policy: str,
    low_signal_window: bool,
) -> dict:
    if len(stage_candidates) == 1:
        return stage_candidates[0]
    policy = str(model_policy).lower()
    if policy == "conservative":
        if low_signal_window:
            ranked = sorted(
                [
                    (
                        _low_signal_model_score(candidate, test_series, history_series),
                        _low_signal_model_priority(candidate.get("name", "")),
                        candidate,
                    )
                    for candidate in stage_candidates
                ],
                key=lambda item: (item[0], item[1]),
            )
            return ranked[0][2]
        ranked = sorted(
            [
                (
                    _conservative_model_score(candidate, test_series),
                    candidate,
                )
                for candidate in stage_candidates
            ],
            key=lambda item: item[0],
        )
        return ranked[0][1]

    wmape_ranked = sorted(stage_candidates, key=lambda item: float(item.get("wmape", float("inf"))))
    if len(wmape_ranked) >= 2:
        top = float(wmape_ranked[0].get("wmape", float("inf")))
        second = float(wmape_ranked[1].get("wmape", float("inf")))
        if np.isfinite(top) and np.isfinite(second) and (second - top) <= 0.025:
            close = [
                candidate
                for candidate in wmape_ranked
                if float(candidate.get("wmape", 9.999)) - top <= 0.025
            ]
            ranked = sorted(
                [
                    (
                        _standard_model_score(candidate, test_series),
                        candidate,
                    )
                    for candidate in close
                ],
                key=lambda item: item[0],
            )
            return ranked[0][1]
    return wmape_ranked[0]


def _build_two_stage_finalists(
    valid_results: list[dict],
    test_series: pd.Series,
    history_series: pd.Series,
    model_policy: str,
    low_signal_window: bool,
) -> list[dict]:
    stage_buckets: dict[str, list[dict]] = {}
    for candidate in valid_results:
        stage = _candidate_stage(candidate)
        stage_buckets.setdefault(stage, []).append(candidate)
    finalists: list[dict] = []
    for stage_name in ["base", "robust", "ensemble"]:
        candidates = stage_buckets.get(stage_name, [])
        if not candidates:
            continue
        finalists.append(
            _select_stage_best(
                candidates,
                test_series=test_series,
                history_series=history_series,
                model_policy=model_policy,
                low_signal_window=low_signal_window,
            )
        )
    if not finalists:
        finalists = list(valid_results)
    return finalists


def _stage_gate_bonus(stage: str, screening: dict, low_signal_window: bool, history_weeks: int) -> float:
    """Lower score is better; negative bonus means preference."""
    stage_name = str(stage).lower()
    zero_ratio = float(screening.get("zero_ratio", 0.0))
    recent_ratio = float(screening.get("recent_to_prior_ratio", 1.0))
    if low_signal_window or zero_ratio >= 0.55 or recent_ratio <= 0.5:
        if stage_name == "robust":
            return -0.05
        if stage_name == "ensemble":
            return 0.03
        return 0.0
    # Strong-signal regime: encourage ensemble slightly, keep robust neutral.
    if history_weeks >= 104 and zero_ratio <= 0.35 and recent_ratio >= 0.8:
        if stage_name == "ensemble":
            return -0.03
        if stage_name == "robust":
            return 0.02
    return 0.0


def _final_candidate_score(
    candidate: dict,
    test_series: pd.Series,
    history_series: pd.Series,
    screening: dict,
    model_policy: str,
    low_signal_window: bool,
    history_weeks: int,
) -> float:
    policy = str(model_policy).lower()
    if policy == "conservative":
        base_score = (
            _low_signal_model_score(candidate, test_series, history_series)
            if low_signal_window
            else _conservative_model_score(candidate, test_series)
        )
    else:
        base_score = _standard_model_score(candidate, test_series)
    return float(base_score + _stage_gate_bonus(_candidate_stage(candidate), screening, low_signal_window, history_weeks))


def _low_signal_model_priority(model_name: str) -> int:
    order = {
        "LowSignalMedian": 0,
        "ZeroAwareNaive": 1,
        "CrostonSBA": 2,
        "SeasonalNaive": 3,
        "AutoARIMA": 4,
        "Ensemble-Weighted": 5,
        "Ensemble-Avg": 6,
        "LightGBM": 7,
        "XGBoost": 8,
        "Prophet": 9,
    }
    return order.get(str(model_name), 99)


def _zero_validation_proxy_error(preds: np.ndarray, train_series: pd.Series) -> float:
    clean_train = pd.Series(train_series).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if clean_train.empty:
        return 9.999
    anchor = float(clean_train.tail(min(12, len(clean_train))).mean())
    anchor = max(anchor, 1.0)
    mae = float(np.mean(np.abs(np.asarray(preds, dtype=float).flatten())))
    if not np.isfinite(mae):
        return 9.999
    return float(min(mae / anchor, 9.999))


def _candidate_quality_metric(candidate: dict) -> float:
    quality = float(candidate.get("quality_score", float(candidate.get("wmape", float("inf")))))
    if not np.isfinite(quality):
        return float("inf")
    return quality


def _prefer_stable_ensemble_near_tie(
    winner: dict,
    finalists: list[dict],
    screening: dict,
    validation_non_zero_points: int,
    low_signal_window: bool,
) -> tuple[dict, str | None]:
    if str(winner.get("name", "")).startswith("Ensemble"):
        return winner, None
    ensemble_candidate = _best_ensemble_candidate(finalists)
    if ensemble_candidate is None:
        return winner, None
    winner_wmape = float(winner.get("wmape", float("inf")))
    ensemble_wmape = float(ensemble_candidate.get("wmape", float("inf")))
    if not (np.isfinite(winner_wmape) and np.isfinite(ensemble_wmape)):
        return winner, None
    zero_ratio = float(screening.get("zero_ratio", 1.0))
    recent_mean = float(screening.get("recent_mean", 0.0))
    if validation_non_zero_points < 6 or zero_ratio > 0.60 or recent_mean <= 0.5:
        return winner, None
    tie_margin = NEAR_TIE_ENSEMBLE_MARGIN + (0.003 if low_signal_window else 0.0)
    if ensemble_wmape > winner_wmape + tie_margin:
        return winner, None
    winner_quality = _candidate_quality_metric(winner)
    ensemble_quality = _candidate_quality_metric(ensemble_candidate)
    if ensemble_quality <= winner_quality + 0.02:
        reason = (
            "near-tie stable ensemble fallback: "
            f"{ensemble_candidate.get('name')} wmape={ensemble_wmape:.4f}, "
            f"quality={ensemble_quality:.4f} vs winner {winner.get('name')} "
            f"wmape={winner_wmape:.4f}, quality={winner_quality:.4f}"
        )
        return ensemble_candidate, reason
    return winner, None


def _apply_dual_metric_guardrail(
    winner: dict,
    finalists: list[dict],
    low_signal_window: bool,
) -> tuple[dict, str | None]:
    finite_finalists = [
        candidate for candidate in finalists if np.isfinite(float(candidate.get("wmape", float("inf"))))
    ]
    if not finite_finalists:
        return winner, None
    best_wmape = min(float(candidate.get("wmape", float("inf"))) for candidate in finite_finalists)
    best_quality = min(_candidate_quality_metric(candidate) for candidate in finite_finalists)
    wmape_margin = DUAL_GUARD_WMAPE_MARGIN_LOW_SIGNAL if low_signal_window else DUAL_GUARD_WMAPE_MARGIN_STANDARD
    quality_margin = DUAL_GUARD_QUALITY_MARGIN_LOW_SIGNAL if low_signal_window else DUAL_GUARD_QUALITY_MARGIN_STANDARD
    dual_pass = [
        candidate
        for candidate in finite_finalists
        if float(candidate.get("wmape", float("inf"))) <= best_wmape + wmape_margin
        and _candidate_quality_metric(candidate) <= best_quality + quality_margin
    ]
    if not dual_pass:
        return winner, None
    winner_name = str(winner.get("name", ""))
    if any(str(candidate.get("name", "")) == winner_name for candidate in dual_pass):
        return winner, None
    replacement = min(
        dual_pass,
        key=lambda candidate: (
            float(candidate.get("wmape", float("inf"))),
            _candidate_quality_metric(candidate),
            _low_signal_model_priority(candidate.get("name", "")),
        ),
    )
    reason = (
        "dual-metric guardrail: "
        f"use {replacement.get('name')} (wmape={float(replacement.get('wmape', float('inf'))):.4f}, "
        f"quality={_candidate_quality_metric(replacement):.4f}) instead of {winner_name} "
        f"(wmape={float(winner.get('wmape', float('inf'))):.4f}, quality={_candidate_quality_metric(winner):.4f})"
    )
    return replacement, reason


def _conservative_shortlist(valid_results: list[dict], wmape_margin: float = 0.015) -> list[dict]:
    finite_candidates = [
        candidate
        for candidate in valid_results
        if np.isfinite(float(candidate.get("wmape", float("inf"))))
    ]
    if not finite_candidates:
        return []
    best_wmape = min(float(candidate.get("wmape", float("inf"))) for candidate in finite_candidates)
    return [
        candidate
        for candidate in finite_candidates
        if float(candidate.get("wmape", float("inf"))) <= best_wmape + wmape_margin
    ]


def _apply_low_signal_post_rules(preds: np.ndarray, history_series: pd.Series, screening: dict) -> np.ndarray:
    adjusted = np.asarray(preds, dtype=float).flatten().copy()
    if adjusted.size == 0:
        return adjusted

    hist = pd.Series(history_series).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if hist.empty:
        return np.maximum(adjusted, 0.0)

    recent = hist.tail(min(12, len(hist)))
    recent_non_zero = recent[recent > 0]
    anchor = float(recent_non_zero.median()) if not recent_non_zero.empty else float(recent.mean())
    anchor = max(anchor, 0.0)
    recent_std = float(recent.std(ddof=0)) if len(recent) > 1 else 0.0
    recent_peak = float(recent.max()) if len(recent) > 0 else anchor

    cap = max(anchor * 2.2, recent_peak * 1.5, anchor + recent_std * 2.5, 1.0)
    adjusted = np.minimum(np.maximum(adjusted, 0.0), cap)

    max_step = max(anchor * 0.6, recent_std * 2.0, 1.0)
    for idx in range(1, len(adjusted)):
        lo = max(adjusted[idx - 1] - max_step, 0.0)
        hi = adjusted[idx - 1] + max_step
        adjusted[idx] = float(np.clip(adjusted[idx], lo, hi))

    if int(screening.get("recent_zero_weeks", 0)) >= 1 and anchor < 30:
        adjusted[0] = min(adjusted[0], anchor * 0.8)

    return np.maximum(adjusted, 0.0)


def process_single_spu(
    spu,
    df_spu,
    mode="smart",
    exog_cols=None,
    collect_viz=False,
    verbose=True,
    sku_accuracy_threshold=0.01,
    log_fn=None,
):
    t0 = time.time()
    try:
        profiler = SPUProfiler(verbose=verbose)
        df_spu_idx = df_spu.set_index("date").sort_index()

        series = df_spu_idx["sales"].resample("W").sum()
        current_week_end = get_current_week_end()
        series = series[series.index < current_week_end]
        original_series = series.copy()

        # Heuristic: if the latest weekly bucket is zero while recent history is active,
        # treat it as an incomplete ingestion week and exclude it from training/validation.
        if len(series) >= 20 and float(series.iloc[-1]) == 0.0:
            recent_active_weeks = int((series.iloc[-5:-1] > 0).sum()) if len(series) >= 5 else 0
            if recent_active_weeks >= 3:
                series = series.iloc[:-1]
                original_series = original_series.iloc[:-1]
                if log_fn is not None:
                    log_fn(f"SPU {spu} detected trailing zero week; trimmed latest week for stable validation.")

        has_exog, exog_series, used_exog = False, None, []
        if exog_cols:
            available = [c for c in exog_cols if c in df_spu_idx.columns]
            if available:
                exog_df = pd.DataFrame(index=series.index)
                if "ad_cost" in available:
                    exog_df["ad_cost"] = df_spu_idx["ad_cost"].resample("W").sum().fillna(0)
                if "price" in available:
                    df_spu_idx["revenue"] = df_spu_idx["sales"] * df_spu_idx["price"]
                    series_price = df_spu_idx["revenue"].resample("W").sum() / series.replace(0, np.nan)
                    exog_df["price"] = series_price.ffill().bfill().fillna(0)

                exog_series = exog_df[exog_df.index < current_week_end]
                has_exog, used_exog = True, available

        if len(series) > MAX_TRAIN_HISTORY_WEEKS:
            series = series.iloc[-MAX_TRAIN_HISTORY_WEEKS:]
            original_series = original_series.iloc[-MAX_TRAIN_HISTORY_WEEKS:]
            if has_exog and exog_series is not None:
                exog_series = exog_series.iloc[-MAX_TRAIN_HISTORY_WEEKS:]
        if has_exog and exog_series is not None:
            exog_series = exog_series.reindex(series.index).ffill().bfill().fillna(0)

        screening = screen_weekly_series(series, min_history_weeks=SCOPE_MIN_HISTORY_WEEKS)
        if screening["insufficient_data"]:
            return None, f"数据不足 ({screening['history_weeks']}周)", None, None

        if screening["recommendation"] == "zero_override" and verbose:
            print(f"   Screening: {screening['recommendation']} | reasons={','.join(screening['reasons'])}")
        elif screening["recommendation"] == "conservative" and verbose:
            print(f"   Screening: {screening['recommendation']} | reasons={','.join(screening['reasons'])}")

        series_clean = clean_series(series)
        if len(series_clean) < 12:
            return None, "数据不足 (<12周)", None, None

        profile = profiler.analyze(spu, series_clean, original_series, exog_series)
        if verbose:
            profiler.print_profile(profile)

        test_len = min(VALIDATION_TEST_MAX_WEEKS, max(VALIDATION_TEST_MIN_WEEKS, len(series_clean) // VALIDATION_TEST_DIVISOR))
        train, test = series_clean.iloc[:-test_len], series_clean.iloc[-test_len:]
        train_exog = exog_series.iloc[:-test_len] if has_exog else None
        test_exog = exog_series.iloc[-test_len:] if has_exog else None
        validation_non_zero_points = int((test > 0).sum())
        validation_total_sales = float(test.sum())
        history_weeks = int(len(series_clean))
        recommendation = str(screening.get("recommendation") or "standard").lower()
        zero_ratio = float(screening.get("zero_ratio", 1.0))
        recent_to_prior_ratio = float(screening.get("recent_to_prior_ratio", 0.0))
        allow_standard_models = bool(screening.get("allow_standard_models", True))
        is_anomalous = bool(screening.get("is_anomalous", False))
        allow_standard_override = str(os.getenv("ALLOW_STANDARD_UNDER_CONSERVATIVE_HINT", "0")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # Two-tier gate:
        # - conservative: only for truly extreme low-signal / collapse scenarios
        # - standard with low-signal guard: for moderate sparse windows, keep full model arena
        extreme_low_signal = (
            recommendation == "zero_override"
            or validation_non_zero_points < CONSERVATIVE_NON_ZERO_MAX
            or validation_total_sales < CONSERVATIVE_TOTAL_SALES_MIN
            or zero_ratio >= CONSERVATIVE_ZERO_RATIO_MIN
            or recent_to_prior_ratio <= CONSERVATIVE_RECENT_RATIO_MAX
        )
        low_signal_window = (
            validation_non_zero_points < LOW_SIGNAL_NON_ZERO_MAX
            or validation_total_sales < LOW_SIGNAL_TOTAL_SALES_MIN
            or recommendation in {"conservative", "zero_override"}
        )
        baseline_conservative = (
            recommendation in {"conservative", "zero_override"}
            or (not allow_standard_models)
            or is_anomalous
        )
        model_policy = (
            "conservative"
            if extreme_low_signal or (baseline_conservative and not allow_standard_override)
            else "standard"
        )
        if log_fn is not None:
            if model_policy == "conservative":
                guardrail_reason = []
                if recommendation in {"conservative", "zero_override"}:
                    guardrail_reason.append(f"recommendation={recommendation}")
                if not allow_standard_models:
                    guardrail_reason.append("allow_standard_models=False")
                if is_anomalous:
                    guardrail_reason.append("is_anomalous=True")
                if allow_standard_override and baseline_conservative and not extreme_low_signal:
                    guardrail_reason.append("override=ALLOW_STANDARD_UNDER_CONSERVATIVE_HINT")
                log_fn(
                    "SPU {} switched to conservative policy: recommendation={}, "
                    "validation_non_zero_points={}, validation_total_sales={:.2f}, "
                    "zero_ratio={:.2f}, recent_to_prior_ratio={:.2f}, guardrail={}.".format(
                        spu,
                        recommendation,
                        validation_non_zero_points,
                        validation_total_sales,
                        zero_ratio,
                        recent_to_prior_ratio,
                        ",".join(guardrail_reason) if guardrail_reason else "none",
                    )
                )
            elif low_signal_window:
                log_fn(
                    "SPU {} stays in standard policy with low-signal guard: recommendation={}, "
                    "validation_non_zero_points={}, validation_total_sales={:.2f}, "
                    "zero_ratio={:.2f}, recent_to_prior_ratio={:.2f}.".format(
                        spu,
                        recommendation,
                        validation_non_zero_points,
                        validation_total_sales,
                        zero_ratio,
                        recent_to_prior_ratio,
                    )
                )
            if model_policy == "standard" and baseline_conservative and allow_standard_override and not extreme_low_signal:
                log_fn(
                    "SPU {} standard override active via ALLOW_STANDARD_UNDER_CONSERVATIVE_HINT: "
                    "recommendation={}, allow_standard_models={}, is_anomalous={}.".format(
                        spu,
                        recommendation,
                        allow_standard_models,
                        is_anomalous,
                    )
                )
        future_dates = pd.date_range(series_clean.index[-1], periods=17, freq="W")[1:]

        if verbose:
            print(f"\nModel competition starting (mode={mode})...")
        if log_fn is not None:
            log_fn(f"SPU {spu} model competition starting, train={len(train)} weeks, test={len(test)} weeks.")
        all_results, base_results = run_all_models(
            train,
            test,
            mode,
            train_exog,
            test_exog,
            verbose=False,
            screening=screening,
            model_policy=model_policy,
            log_fn=(lambda message: log_fn(f"SPU {spu} | {message}")) if log_fn is not None else None,
        )
        valid_results = [result for result in all_results if np.isfinite(result.get("wmape", float("inf")))]
        if not valid_results:
            fallback_pred_test = np.full(len(test), float(test.mean()) if test.mean() > 0 else float(series_clean.mean()))
            fallback_wmape = float(
                np.sum(np.abs(test.values - fallback_pred_test)) / np.sum(np.abs(test.values))
                if (test > 0).sum() >= 4 and np.any(test.values != 0)
                else 9.999
            )
            winner = {"name": "NaiveMean", "forecast": fallback_pred_test.tolist(), "wmape": fallback_wmape, "params": {}}
            all_results = [winner]
        else:
            all_results = valid_results
            finalists = _build_two_stage_finalists(
                valid_results=valid_results,
                test_series=test,
                history_series=series_clean,
                model_policy=model_policy,
                low_signal_window=low_signal_window,
            )
            if log_fn is not None:
                finalist_text = ", ".join(
                    [
                        f"{item.get('name')}[{_candidate_stage(item)}|wmape={float(item.get('wmape', float('inf'))):.4f}]"
                        for item in finalists
                    ]
                )
                log_fn(f"SPU {spu} stage finalists: {finalist_text}.")
            if model_policy == "conservative":
                wmape_best_candidate = min(finalists, key=lambda item: float(item.get("wmape", float("inf"))))
                ranked = sorted(
                    [
                        (
                            _final_candidate_score(
                                candidate=candidate,
                                test_series=test,
                                history_series=series_clean,
                                screening=screening,
                                model_policy=model_policy,
                                low_signal_window=low_signal_window,
                                history_weeks=history_weeks,
                            ),
                            _low_signal_model_priority(candidate.get("name", "")),
                            candidate,
                        )
                        for candidate in finalists
                    ],
                    key=lambda item: (item[0], item[1]),
                )
                winner = ranked[0][2]
                if log_fn is not None:
                    score_text = ", ".join([f"{item[2]['name']}={item[0]:.4f}" for item in ranked[:4]])
                    log_fn(f"SPU {spu} conservative final ranking: {score_text}.")

                winner_wmape = float(winner.get("wmape", float("inf")))
                wmape_best_value = float(wmape_best_candidate.get("wmape", float("inf")))
                if np.isfinite(winner_wmape) and np.isfinite(wmape_best_value):
                    guard_margin = 0.02 if low_signal_window else 0.015
                    if winner_wmape > wmape_best_value + guard_margin:
                        winner = wmape_best_candidate
                        if log_fn is not None:
                            log_fn(
                                f"SPU {spu} conservative wmape guardrail activated: "
                                f"use {winner['name']} ({wmape_best_value:.4f}) "
                                f"instead of higher-error candidate ({winner_wmape:.4f})."
                            )
                # Hybrid bridge: when signal is not extremely sparse, allow
                # stable ensemble to win if its error is close to conservative winner.
                ensemble_candidate = _best_ensemble_candidate(finalists)
                if ensemble_candidate is not None:
                    winner_wmape = float(winner.get("wmape", float("inf")))
                    ensemble_wmape = float(ensemble_candidate.get("wmape", float("inf")))
                    hybrid_ready = (
                        validation_non_zero_points >= 8
                        and float(screening.get("zero_ratio", 1.0)) <= 0.45
                        and float(screening.get("recent_mean", 0.0)) >= 1.0
                    )
                    if (
                        hybrid_ready
                        and np.isfinite(winner_wmape)
                        and np.isfinite(ensemble_wmape)
                        and ensemble_wmape <= winner_wmape + 0.02
                    ):
                        winner = ensemble_candidate
                        if log_fn is not None:
                            log_fn(
                                f"SPU {spu} hybrid override enabled: "
                                f"choose {winner['name']} ({ensemble_wmape:.4f}) "
                                f"over conservative winner ({winner_wmape:.4f})."
                            )
                winner, near_tie_reason = _prefer_stable_ensemble_near_tie(
                    winner=winner,
                    finalists=finalists,
                    screening=screening,
                    validation_non_zero_points=validation_non_zero_points,
                    low_signal_window=low_signal_window,
                )
                if near_tie_reason and log_fn is not None:
                    log_fn(f"SPU {spu} {near_tie_reason}.")
                winner, dual_reason = _apply_dual_metric_guardrail(
                    winner=winner,
                    finalists=finalists,
                    low_signal_window=low_signal_window,
                )
                if dual_reason and log_fn is not None:
                    log_fn(f"SPU {spu} {dual_reason}.")

                # Zero-validation-window fallback:
                # when all validation points are zero, regular WMAPE is not informative.
                if validation_non_zero_points == 0:
                    preferred = ["ZeroAwareNaive", "LowSignalMedian", "CrostonSBA", "SeasonalNaive"]
                    fallback = None
                    for model_name in preferred:
                        fallback = next((item for item in finalists if item.get("name") == model_name), None)
                        if fallback is not None:
                            break
                    if fallback is not None:
                        winner = fallback
                    # Replace capped WMAPE with proxy error ratio for observability.
                    proxy_wmape = _zero_validation_proxy_error(np.asarray(winner.get("preds", []), dtype=float), train)
                    winner = dict(winner)
                    winner["wmape"] = proxy_wmape
                    winner["wmape_metric"] = "proxy_zero_validation"
                    if log_fn is not None:
                        log_fn(
                            f"SPU {spu} zero-validation fallback: choose {winner['name']} "
                            f"with proxy error ratio {proxy_wmape:.4f} (validation_non_zero_points=0)."
                        )
            else:
                ranked = sorted(
                    [
                        (
                            _final_candidate_score(
                                candidate=candidate,
                                test_series=test,
                                history_series=series_clean,
                                screening=screening,
                                model_policy=model_policy,
                                low_signal_window=low_signal_window,
                                history_weeks=history_weeks,
                            ),
                            candidate,
                        )
                        for candidate in finalists
                    ],
                    key=lambda item: item[0],
                )
                winner = ranked[0][1]
                winner, near_tie_reason = _prefer_stable_ensemble_near_tie(
                    winner=winner,
                    finalists=finalists,
                    screening=screening,
                    validation_non_zero_points=validation_non_zero_points,
                    low_signal_window=low_signal_window,
                )
                winner, dual_reason = _apply_dual_metric_guardrail(
                    winner=winner,
                    finalists=finalists,
                    low_signal_window=low_signal_window,
                )
                if log_fn is not None:
                    score_text = ", ".join([f"{item[1]['name']}={item[0]:.4f}" for item in ranked[:4]])
                    log_fn(f"SPU {spu} standard final ranking: {score_text}.")
                    if near_tie_reason:
                        log_fn(f"SPU {spu} {near_tie_reason}.")
                    if dual_reason:
                        log_fn(f"SPU {spu} {dual_reason}.")

        future_exog = None
        if has_exog and exog_series is not None:
            future_dates_exog = pd.date_range(series_clean.index[-1], periods=17, freq="W")[1:]
            future_exog = build_future_exog_frame(exog_series, future_dates_exog)

        final_preds = predict_future(
            series_clean,
            winner,
            16,
            exog_series,
            future_exog,
            base_results,
            screening=screening,
        )

        hist_cv = series_clean.std() / series_clean.mean() if series_clean.mean() > 0 else 0
        pred_cv = np.std(final_preds) / np.mean(final_preds) if np.mean(final_preds) > 0 else 0
        if verbose:
            print(f"   Volatility check: histCV={hist_cv:.3f}, predCV={pred_cv:.3f}, ratio={pred_cv / hist_cv:.2f}")
        if log_fn is not None:
            log_fn(f"SPU {spu} winner model: {winner['name']}, validation WMAPE {winner['wmape']:.2%}.")
            log_fn(f"SPU {spu} forecast generated for {len(future_dates)} future weeks.")
        if pred_cv < hist_cv * 0.3:
            if verbose:
                print("   Warning: forecast volatility is unusually low; fallback smoothing will be applied.")

        fallback_value = float(series_clean.iloc[-8:].mean())
        final_preds = safe_predictions(final_preds, fallback_value, winner["name"], history_series=series_clean)
        if model_policy == "conservative":
            final_preds = _apply_low_signal_post_rules(final_preds, series_clean, screening)

        total_time = time.time() - t0
        profile = profiler.update_with_results(profile, train, test, all_results, winner, final_preds, total_time)

        if verbose:
            profiler.print_model_competition(profile)
            profiler.print_forecast_summary(profile, future_dates, final_preds)

        share_json_list, share_df = calculate_dynamic_shares(df_spu_idx, spu, series_clean, future_dates)
        principal_share_json_list, _principal_share_df = calculate_principal_dynamic_shares(
            df_spu_idx, series_clean, future_dates
        )
        seasonal_factors_json = extract_seasonal_factors_52week(series_clean, period=52)

        sku_accuracy_json = None
        try:
            val_dates = test.index
            train_end_date = val_dates[0] - pd.Timedelta(days=1)
            df_train_idx = df_spu_idx[df_spu_idx.index <= train_end_date]
            train_spu_sales = series_clean[series_clean.index <= train_end_date]

            _, val_share_df = calculate_dynamic_shares(df_train_idx, spu, train_spu_sales, val_dates)
            winner_val_preds = pd.Series(winner["forecast"], index=val_dates)
            sku_val_preds = val_share_df.multiply(winner_val_preds, axis=0)

            sku_val_actual = (
                df_spu_idx[df_spu_idx.index.isin(val_dates)]
                .groupby([pd.Grouper(freq="W"), "sku"])["sales"]
                .sum()
                .unstack(fill_value=0)
            )
            sku_val_actual = sku_val_actual.reindex(index=val_dates, columns=sku_val_preds.columns, fill_value=0)

            sku_metrics = {}
            total_sku_sales = float(sku_val_actual.sum().sum())

            for sku in sku_val_preds.columns:
                actual = sku_val_actual[sku]
                pred = sku_val_preds[sku]
                sku_total = float(actual.sum())
                if total_sku_sales > 0 and sku_total / total_sku_sales < sku_accuracy_threshold:
                    continue

                actual_arr = np.asarray(actual)
                pred_arr = np.asarray(pred)
                mask = actual_arr != 0
                wmape = float(np.sum(np.abs(actual_arr[mask] - pred_arr[mask])) / np.sum(np.abs(actual_arr[mask]))) if np.any(mask) else 0.0
                sku_metrics[sku] = {
                    "wmape": round(wmape, 4),
                    "total_sales": sku_total,
                    "weight_in_spu": round(sku_total / total_sku_sales, 4) if total_sku_sales > 0 else 0,
                }

            sku_accuracy_json = json.dumps(sku_metrics, ensure_ascii=False)
        except Exception as exc:
            if verbose:
                print(f"   SKU 璇勪及澶辫触: {exc}")
            sku_accuracy_json = json.dumps({"error": str(exc)}, ensure_ascii=False)

        sku_future_df = share_df.multiply(final_preds, axis=0)
        safe_best_params = clean_params_for_db(winner.get("params"))

        result_df = pd.DataFrame(
            {
                "spu": spu,
                "run_date": datetime.date.today(),
                "forecast_target_date": [d.date() for d in future_dates],
                "spu_forecast_value": np.round(final_preds, 4),
                "sku_share_json": share_json_list,
                "principal_share_json": principal_share_json_list,
                "seasonal_factors_json": seasonal_factors_json,
                "sku_accuracy_json": sku_accuracy_json,
                "winner_algo": winner["name"],
                "validation_wmape": round(winner["wmape"], 4),
                "best_params": safe_best_params,
                "has_exog_features": has_exog,
                "exog_columns": ",".join(used_exog) if used_exog else None,
                "training_weeks": int(len(series_clean)),
                "data_end_date": series_clean.index[-1].date(),
            }
        )

        viz_data = (
            {
                "profile": profile,
                "train": train,
                "test": test,
                "results": all_results,
                "future": final_preds,
                "dates": future_dates,
                "winner": winner,
                "sku_future_df": sku_future_df,
            }
            if collect_viz
            else None
        )

        if collect_viz and verbose:
            plot_best_spu_style(
                profile,
                train,
                test,
                all_results,
                final_preds,
                future_dates,
                sku_future_df=sku_future_df,
                save_path=None,
                show_plot=True,
            )

        return (
            result_df,
            f"{winner['name']} (WMAPE: {winner['wmape']:.2%}, policy={model_policy}) [{total_time:.1f}s]",
            viz_data,
            profile,
        )
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return None, f"閿欒: {str(exc)}", None, None


def save_to_database(*args, **kwargs):
    return _load_legacy_kernel().save_to_database(*args, **kwargs)


def main(*args, **kwargs):
    return _load_legacy_kernel().main(*args, **kwargs)
