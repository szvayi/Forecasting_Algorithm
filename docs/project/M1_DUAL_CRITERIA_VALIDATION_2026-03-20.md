# M1 双标准验收记录（2026-03-20）

## 验收标准（主人确认）
1. 是否成功调用后端核心程序 `main`（核心处理链路）。
2. 是否最终成功入库（`sales_forecast_history` 可查到本次运行数据）。

## 执行方式
- 脚本：`tools/ad_hoc/m1_dual_criteria_check.py`
- 运行模式：`fast`
- 选择方式：`all`（通过环境变量 `SPU_LIST` 锁定单 SPU，降低验证范围）
- 数据库：`SALES_FORECAST_DB_URL`（PostgreSQL）

## 三次结果（已完成 3/3）
| 次数 | run_id | selected_spu_for_test | final_status | success_count | db_rows_for_run_id | 标准1(main链路) | 标准2(入库) |
|---|---|---|---|---:|---:|---|---|
| 1 | `ecce320ec5ca4c24aaa4de9a8a2da8f8` | `2165` | `completed` | 1 | 16 | PASS | PASS |
| 2 | `a696ddf0d41449089d3ddeb7d6c7d1e1` | `2165` | `completed` | 1 | 16 | PASS | PASS |
| 3 | `50473622f7e5473ebc5f4bcc205727e8` | `2165` | `completed` | 1 | 16 | PASS | PASS |

结论：双标准连续三次通过。

## 证据摘录
- 运行日志包含：
  - `Run <run_id> started in fast mode.`
  - `Processing SPU 2165 (1/1).`
  - `Saved 16 forecast rows to the database.`
  - `Run completed.`
- 数据库查询（按各自 `run_id`）均返回 16 行，说明三次入库成功且可检索。

## 本轮修复（为保证验收可执行）
- `algorithm_engine.py`
  - 移除 Windows 控制台不兼容的 emoji 打印，避免编码异常中断。
  - ARIMA 结果判定增加结构健壮性，避免 `KeyError` 造成单 SPU 失败。
- `src/database/repositories.py`
  - `query_forecast_results` 在查询前自动补齐 `run_id/config_id` 字段，兼容历史库结构。

## 算法执行到位性（本轮重点）
- 已执行并产出结果：
  - `XGBoost`（WMAPE 约 62.41%）
  - `LightGBM`（WMAPE 约 35.05%）
  - `CatBoost`（WMAPE 约 32.10%）
  - `Ensemble`（Done, 2 methods）
- 未执行到位：
  - `Prophet`：持续失败，报错 `Prophet object has no attribute stan_backend`
  - `ARIMA`：持续失败（超时/不可用）

### 补充复核（2026-03-20）
- 复核 `run_id`: `f82bbc38cd39416dafb65c9fcb7054d6`
- 双标准结果：仍为 PASS（`main` 调用成功 + 入库 16 行）
- 算法侧更精确结论：
  - `Prophet`：`Prophet backend unavailable: 'Prophet' object has no attribute 'stan_backend'`
  - `ARIMA`：`Timeout after 45s`（fast 模式下仍超时）

### M2 修复后复核（2026-03-20）
- 复核 `run_id`: `dbe0403a648d4c56bf5a642544d15dc2`
- 双标准结果：PASS（`main` 调用成功 + 入库 16 行）
- 算法执行结论更新：
  - `Prophet`：已不再中断流程，改为可执行的 fallback 路径（当前 WMAPE 较高，后续继续优化）
  - `ARIMA`：fast 模式已执行到位，日志显示 `Done (order=(1, 1, 0))`
  - `SARIMA+LSTM`：shape 问题已修复，已执行并产出（示例 WMAPE 约 45.49%）

### 最新验证（2026-03-20）
- `run_id`: `35f428ff14d74efe9537c7f771bdfc8b`
- 双标准：PASS（`main` 调用成功 + 入库 16 行）
- 算法覆盖（fast）：
  - Prophet（fallback）✅
  - XGBoost ✅
  - LightGBM ✅
  - CatBoost ✅
  - ARIMA ✅
  - SARIMA+LSTM ✅

## 结论
M1 双标准门禁已连续三次通过，核心闭环成立且稳定。  
当前遗留是“部分算法可用性问题”（Prophet、ARIMA），不阻塞 M1 闭环通过，但应进入 M2 的算法稳定性修复清单。
