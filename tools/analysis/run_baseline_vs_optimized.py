#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""基线版 vs 优化版 预测效果可复现实验脚本（不增加数据）"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports" / "generated"
MARKER = "AB_RESULT_JSON="


def _run(cmd: List[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _resolve_ref(ref: str) -> str:
    return _run(["git", "rev-parse", "--verify", ref], cwd=ROOT_DIR).strip()


def _inline_runner() -> str:
    # 在不同 worktree 上运行同一段代码，确保口径一致。
    return r"""
import json
import os
import traceback
import numpy as np
import pandas as pd

from src.forecasting.kernel import get_data_from_db, process_single_spu

mode = os.getenv("AB_MODE", "smart")
max_spus_env = os.getenv("AB_MAX_SPUS", "").strip()
spu_list_env = os.getenv("AB_SPU_LIST", "").strip()
db_url = os.getenv("SALES_FORECAST_DB_URL", "").strip()

if not db_url:
    raise RuntimeError("SALES_FORECAST_DB_URL is required")

max_spus = int(max_spus_env) if max_spus_env else 0

df_all = get_data_from_db(db_url)
if df_all is None or df_all.empty:
    raise RuntimeError("No data loaded from DB")

df_all["sales"] = pd.to_numeric(df_all["sales"], errors="coerce").fillna(0.0)
df_all["date"] = pd.to_datetime(df_all["date"], errors="coerce")
df_all = df_all.dropna(subset=["date"]).copy()
df_all["spu"] = df_all["spu"].astype(str)
df_all["sku"] = df_all["sku"].astype(str)

exog_cols = [c for c in df_all.columns if c in ("ad_cost", "price")]

if spu_list_env:
    target_spus = [s.strip() for s in spu_list_env.split(",") if s.strip()]
else:
    target_spus = sorted(df_all["spu"].unique().tolist())

if max_spus > 0:
    target_spus = target_spus[:max_spus]

records = []
failures = []

for spu in target_spus:
    df_spu = df_all[df_all["spu"] == spu].copy()
    try:
        result_df, message, _viz, _profile = process_single_spu(
            spu=spu,
            df_spu=df_spu,
            mode=mode,
            exog_cols=exog_cols,
            collect_viz=False,
            verbose=False,
        )
        if result_df is None or result_df.empty:
            failures.append({"spu": spu, "message": str(message)})
            continue
        first_row = result_df.iloc[0]
        wmape = float(first_row.get("validation_wmape", np.nan))
        winner_algo = str(first_row.get("winner_algo", ""))
        training_weeks = int(first_row.get("training_weeks", 0))
        records.append(
            {
                "spu": spu,
                "validation_wmape": wmape,
                "winner_algo": winner_algo,
                "training_weeks": training_weeks,
                "message": str(message),
            }
        )
    except Exception as exc:
        failures.append({"spu": spu, "message": f"{exc}"})

result_df = pd.DataFrame(records)
if result_df.empty:
    summary = {
        "sample_count": 0,
        "mean_wmape_pct": None,
        "median_wmape_pct": None,
        "p75_wmape_pct": None,
        "p90_wmape_pct": None,
        "gt40_count": 0,
        "gt50_count": 0,
        "failure_count": len(failures),
        "mode": mode,
        "spu_scope_count": len(target_spus),
    }
else:
    w = result_df["validation_wmape"].astype(float).clip(lower=0.0)
    summary = {
        "sample_count": int(len(result_df)),
        "mean_wmape_pct": float(w.mean() * 100.0),
        "median_wmape_pct": float(w.median() * 100.0),
        "p75_wmape_pct": float(w.quantile(0.75) * 100.0),
        "p90_wmape_pct": float(w.quantile(0.90) * 100.0),
        "gt40_count": int((w > 0.40).sum()),
        "gt50_count": int((w > 0.50).sum()),
        "failure_count": len(failures),
        "mode": mode,
        "spu_scope_count": len(target_spus),
    }

winner_distribution = (
    result_df["winner_algo"].value_counts(dropna=False).to_dict() if not result_df.empty else {}
)

payload = {
    "summary": summary,
    "winner_distribution": winner_distribution,
    "records": records,
    "failures": failures,
}
print("AB_RESULT_JSON=" + json.dumps(payload, ensure_ascii=True))
"""


def _parse_marker_output(stdout: str) -> Dict[str, object]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER):].strip())
    raise RuntimeError("子进程输出中未找到 AB_RESULT_JSON 标记")


def _run_variant(ref: str, db_url: str, mode: str, max_spus: int, spu_list: str) -> Dict[str, object]:
    resolved_ref = _resolve_ref(ref)
    temp_root = Path(tempfile.mkdtemp(prefix="ab_ref_"))
    worktree = temp_root / "repo"
    try:
        _run(["git", "worktree", "add", "--detach", str(worktree), resolved_ref], cwd=ROOT_DIR)
        env = os.environ.copy()
        env["SALES_FORECAST_DB_URL"] = db_url
        env["AB_MODE"] = mode
        env["AB_MAX_SPUS"] = str(max_spus) if max_spus > 0 else ""
        env["AB_SPU_LIST"] = spu_list or ""
        try:
            completed = subprocess.run(
                [sys.executable, "-c", _inline_runner()],
                cwd=str(worktree),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            stdout = exc.stdout or ""
            raise RuntimeError(
                "Variant run failed: "
                f"ref={ref}, code={exc.returncode}, "
                f"stdout_tail={stdout[-800:]}, stderr_tail={stderr[-1200:]}"
            ) from exc
        payload = _parse_marker_output(completed.stdout)
        payload["git_ref_input"] = ref
        payload["git_ref_resolved"] = resolved_ref
        return payload
    finally:
        try:
            _run(["git", "worktree", "remove", "--force", str(worktree)], cwd=ROOT_DIR)
        except Exception:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def _build_compare(baseline_payload: Dict[str, object], optimized_payload: Dict[str, object]) -> Dict[str, object]:
    baseline_summary = baseline_payload["summary"]
    optimized_summary = optimized_payload["summary"]

    b_map = {item["spu"]: item for item in baseline_payload.get("records", [])}
    o_map = {item["spu"]: item for item in optimized_payload.get("records", [])}
    common_spus = sorted(set(b_map.keys()) & set(o_map.keys()))

    improved = 0
    worsened = 0
    same = 0
    per_spu = []
    for spu in common_spus:
        b_w = float(b_map[spu]["validation_wmape"])
        o_w = float(o_map[spu]["validation_wmape"])
        delta = b_w - o_w
        if delta > 1e-6:
            improved += 1
            trend = "improved"
        elif delta < -1e-6:
            worsened += 1
            trend = "worsened"
        else:
            same += 1
            trend = "same"
        per_spu.append(
            {
                "spu": spu,
                "baseline_wmape_pct": round(b_w * 100.0, 4),
                "optimized_wmape_pct": round(o_w * 100.0, 4),
                "delta_wmape_pct": round(delta * 100.0, 4),
                "trend": trend,
                "baseline_winner": b_map[spu].get("winner_algo"),
                "optimized_winner": o_map[spu].get("winner_algo"),
            }
        )

    mean_delta = None
    if baseline_summary.get("mean_wmape_pct") is not None and optimized_summary.get("mean_wmape_pct") is not None:
        mean_delta = round(float(baseline_summary["mean_wmape_pct"]) - float(optimized_summary["mean_wmape_pct"]), 4)

    return {
        "comparison_scope": {
            "common_spu_count": len(common_spus),
            "baseline_sample_count": baseline_summary.get("sample_count"),
            "optimized_sample_count": optimized_summary.get("sample_count"),
        },
        "headline": {
            "mean_wmape_delta_pct": mean_delta,
            "improved_count": improved,
            "worsened_count": worsened,
            "same_count": same,
        },
        "metric_fields": [
            "sample_count",
            "failure_count",
            "mean_wmape_pct",
            "median_wmape_pct",
            "p75_wmape_pct",
            "p90_wmape_pct",
            "gt40_count",
            "gt50_count",
            "winner_distribution",
        ],
        "per_spu": per_spu,
    }


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_interpretation_md(
    baseline_path: Path,
    optimized_path: Path,
    compare_path: Path,
    baseline_ref: str,
    optimized_ref: str,
) -> str:
    return f"""# Baseline vs Optimized 结果解读模板

## 1) 实验信息
- Baseline Ref: `{baseline_ref}`
- Optimized Ref: `{optimized_ref}`
- Baseline 结果文件: `{baseline_path.as_posix()}`
- Optimized 结果文件: `{optimized_path.as_posix()}`
- 对比结果文件: `{compare_path.as_posix()}`

## 2) 先看稳定性（硬门槛）
- `sample_count`：优化版不应明显下降（建议 >= baseline 的 95%）
- `failure_count`：优化版不应上升
- `gt50_count`：优化版不应高于 baseline

## 3) 再看核心效果（软目标）
- `mean_wmape_pct`：是否下降（越低越好）
- `median_wmape_pct`：是否下降
- `p75_wmape_pct` / `p90_wmape_pct`：长尾是否收敛
- `gt40_count`：高误差 SPU 是否减少

## 4) SPU 层判断
- `trend=improved` 的数量是否显著高于 `worsened`
- 对 `worsened` 的 SPU，优先看：
  1. `baseline_winner` vs `optimized_winner` 是否切换
  2. 是否集中在低信号样本（训练周数较短或近期断崖）

## 5) 结论模板（可直接替换）
> 在同一数据与相同 SPU 范围下，优化版相对 baseline：
> - 样本覆盖：`{{sample_delta}}`
> - 平均误差：`{{mean_delta}}`
> - 长尾误差：`{{tail_delta}}`
> - SPU 维度：`improved={{improved}} / worsened={{worsened}} / same={{same}}`
> 结论：`{{go_no_go}}`（建议：通过 / 有条件通过 / 不通过）
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible baseline-vs-optimized validation.")
    parser.add_argument("--baseline-ref", default="HEAD~1", help="Git ref for baseline variant.")
    parser.add_argument("--optimized-ref", default="HEAD", help="Git ref for optimized variant.")
    parser.add_argument("--db-url", default=os.getenv("SALES_FORECAST_DB_URL", ""), help="Database URL.")
    parser.add_argument("--mode", default="smart", choices=["fast", "smart", "full"], help="Forecast mode.")
    parser.add_argument("--max-spus", type=int, default=0, help="Limit SPU count for smoke/quick run (0=all).")
    parser.add_argument("--spu-list", default="", help="Comma-separated SPU whitelist.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for result files.")
    parser.add_argument("--tag", default="", help="Optional output tag.")
    args = parser.parse_args()

    if not args.db_url:
        raise SystemExit("Missing DB URL: pass --db-url or set SALES_FORECAST_DB_URL.")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = args.tag.strip() or f"ab_repro_{ts}"

    baseline_payload = _run_variant(
        ref=args.baseline_ref,
        db_url=args.db_url,
        mode=args.mode,
        max_spus=args.max_spus,
        spu_list=args.spu_list,
    )
    optimized_payload = _run_variant(
        ref=args.optimized_ref,
        db_url=args.db_url,
        mode=args.mode,
        max_spus=args.max_spus,
        spu_list=args.spu_list,
    )
    compare_payload = _build_compare(baseline_payload, optimized_payload)

    baseline_path = output_dir / f"{tag}_baseline_result.json"
    optimized_path = output_dir / f"{tag}_optimized_result.json"
    compare_path = output_dir / f"{tag}_compare_result.json"
    template_path = output_dir / f"{tag}_interpretation_template.md"

    _write_json(baseline_path, baseline_payload)
    _write_json(optimized_path, optimized_payload)
    _write_json(compare_path, compare_payload)
    template_path.write_text(
        _build_interpretation_md(
            baseline_path=baseline_path,
            optimized_path=optimized_path,
            compare_path=compare_path,
            baseline_ref=args.baseline_ref,
            optimized_ref=args.optimized_ref,
        ),
        encoding="utf-8",
    )

    summary = {
        "baseline_ref": args.baseline_ref,
        "optimized_ref": args.optimized_ref,
        "mode": args.mode,
        "max_spus": args.max_spus,
        "spu_list": args.spu_list,
        "files": {
            "baseline": str(baseline_path),
            "optimized": str(optimized_path),
            "compare": str(compare_path),
            "interpretation_template": str(template_path),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
