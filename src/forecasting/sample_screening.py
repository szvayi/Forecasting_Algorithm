"""Weekly forecast sample screening and anomaly diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List
import os

import numpy as np
import pandas as pd


def _safe_env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return int(default)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _safe_env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


DEFAULT_SCREENING_MIN_HISTORY_WEEKS = _safe_env_int(
    "SCREENING_MIN_HISTORY_WEEKS",
    _safe_env_int("SCOPE_MIN_WEEKS", 108),
)
DEFAULT_COLLAPSE_RATIO = _safe_env_float("SCREENING_COLLAPSE_RATIO_BASE", 0.35)
DEFAULT_COLLAPSE_RATIO_STRICT = _safe_env_float("SCREENING_COLLAPSE_RATIO_STRICT", 0.45)
DEFAULT_COLLAPSE_RATIO_LOOSE = _safe_env_float("SCREENING_COLLAPSE_RATIO_LOOSE", 0.28)


@dataclass
class SampleScreeningResult:
    history_weeks: int
    min_history_weeks: int
    qualified_min_history: bool
    qualified_156_weeks: bool
    insufficient_data: bool
    zero_ratio: float
    recent_zero_weeks: int
    recent_zero_ratio: float
    recent_mean: float
    prior_mean: float
    recent_to_prior_ratio: float
    max_zero_run: int
    has_recent_zero_tail: bool
    is_anomalous: bool
    allow_standard_models: bool
    recommendation: str
    collapse_ratio_used: float
    reasons: List[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _longest_zero_run(values: pd.Series) -> int:
    longest = 0
    current = 0
    for value in values.astype(float).fillna(0.0).to_numpy():
        if float(value) == 0.0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _safe_mean(values: pd.Series) -> float:
    clean = pd.Series(values).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return 0.0
    return float(clean.mean())


def _resolve_collapse_ratio(history_weeks: int, zero_ratio: float, base_ratio: float) -> float:
    # More sensitive on sparse/zero-heavy windows; less sensitive on long stable history.
    ratio = float(base_ratio)
    if history_weeks < 96 or zero_ratio >= 0.60:
        ratio = max(ratio, DEFAULT_COLLAPSE_RATIO_STRICT)
    elif history_weeks >= 140 and zero_ratio <= 0.45:
        ratio = min(ratio, DEFAULT_COLLAPSE_RATIO_LOOSE)
    return float(max(0.15, min(ratio, 0.65)))


def screen_weekly_series(
    series: pd.Series,
    min_history_weeks: int | None = None,
    recent_window: int = 12,
    zero_tail_weeks: int = 4,
    collapse_ratio: float = DEFAULT_COLLAPSE_RATIO,
) -> Dict[str, object]:
    """Analyze sample sufficiency and recent abnormal behavior."""
    min_history_weeks = int(min_history_weeks or DEFAULT_SCREENING_MIN_HISTORY_WEEKS)

    clean = pd.Series(series).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    history_weeks = int(len(clean))

    if history_weeks == 0:
        result = SampleScreeningResult(
            history_weeks=0,
            min_history_weeks=min_history_weeks,
            qualified_min_history=False,
            qualified_156_weeks=False,
            insufficient_data=True,
            zero_ratio=1.0,
            recent_zero_weeks=0,
            recent_zero_ratio=1.0,
            recent_mean=0.0,
            prior_mean=0.0,
            recent_to_prior_ratio=0.0,
            max_zero_run=0,
            has_recent_zero_tail=True,
            is_anomalous=True,
            allow_standard_models=False,
            recommendation="insufficient_data",
            collapse_ratio_used=float(collapse_ratio),
            reasons=["empty_series"],
        )
        return result.to_dict()

    recent_window = max(4, min(int(recent_window), history_weeks))
    tail = clean.tail(recent_window)
    if history_weeks > recent_window:
        prior_start = max(history_weeks - (recent_window * 2), 0)
        prior = clean.iloc[prior_start : history_weeks - recent_window]
    else:
        prior = pd.Series(dtype=float)

    zero_ratio = float((clean == 0).mean())
    recent_zero_weeks = int((tail == 0).sum())
    recent_zero_ratio = float(recent_zero_weeks / len(tail)) if len(tail) > 0 else 1.0
    recent_mean = _safe_mean(tail)
    prior_mean = _safe_mean(prior)
    recent_to_prior_ratio = float(recent_mean / prior_mean) if prior_mean > 0 else (0.0 if recent_mean == 0 else float("inf"))
    max_zero_run = _longest_zero_run(clean)
    has_recent_zero_tail = recent_zero_weeks >= zero_tail_weeks
    qualified_min_history = history_weeks >= min_history_weeks
    # Backward-compatible semantic: this field should always mean >=156 weeks.
    qualified_156_weeks = history_weeks >= 156
    collapse_ratio_used = _resolve_collapse_ratio(
        history_weeks=history_weeks,
        zero_ratio=zero_ratio,
        base_ratio=collapse_ratio,
    )

    reasons: List[str] = []
    if not qualified_min_history:
        reasons.append("history_weeks_below_min_history")
    if not qualified_156_weeks:
        reasons.append("history_weeks_below_156")
    if zero_ratio >= 0.75:
        reasons.append("high_zero_ratio")
    if has_recent_zero_tail:
        reasons.append("recent_zero_tail")
    if max_zero_run >= 8:
        reasons.append("long_zero_run")
    if prior_mean > 0 and recent_mean / prior_mean <= collapse_ratio_used:
        reasons.append("recent_collapse")
        reasons.append(f"collapse_ratio_used={collapse_ratio_used:.2f}")
    if prior_mean > 0 and recent_mean == 0 and recent_zero_weeks >= zero_tail_weeks:
        reasons.append("recent_demand_drop_to_zero")

    is_anomalous = any(
        [
            has_recent_zero_tail and prior_mean > 0,
            max_zero_run >= 8,
            prior_mean > 0 and recent_mean == 0 and recent_zero_weeks >= zero_tail_weeks,
            prior_mean > 0 and recent_mean > 0 and recent_to_prior_ratio <= collapse_ratio_used,
        ]
    )

    allow_standard_models = qualified_min_history and not is_anomalous
    if not qualified_min_history:
        recommendation = "insufficient_data"
    elif is_anomalous:
        recommendation = (
            "zero_override"
            if recent_mean == 0 or recent_to_prior_ratio <= collapse_ratio_used
            else "conservative"
        )
    else:
        recommendation = "standard"

    return SampleScreeningResult(
        history_weeks=history_weeks,
        min_history_weeks=min_history_weeks,
        qualified_min_history=qualified_min_history,
        qualified_156_weeks=qualified_156_weeks,
        insufficient_data=history_weeks < 12,
        zero_ratio=zero_ratio,
        recent_zero_weeks=recent_zero_weeks,
        recent_zero_ratio=recent_zero_ratio,
        recent_mean=recent_mean,
        prior_mean=prior_mean,
        recent_to_prior_ratio=recent_to_prior_ratio,
        max_zero_run=max_zero_run,
        has_recent_zero_tail=has_recent_zero_tail,
        is_anomalous=is_anomalous,
        allow_standard_models=allow_standard_models,
        recommendation=recommendation,
        collapse_ratio_used=collapse_ratio_used,
        reasons=reasons,
    ).to_dict()
