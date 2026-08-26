# 如何查看“SPU vs SKU 误差率对比”结果

本指南回答两个问题：
1) 如何看到某个 SPU 的误差率（SPU 级）与其下各 SKU 的误差率（SKU 级）对比  
2) 如何验证“SPU×动态份额”拆分方式对 SKU 是否偏差较大  

## 1. 先跑一遍预测任务（生成并写入结果）
运行入口在 [main.py](file:///c:/Users/VY0814/Forecasting_Algorithm/main.py)。当开启写库时，会写入表 `finedatalink.sales_forecast_history`。

关键字段：
- SPU 级误差：`validation_wmape`
- SKU 级误差明细：`sku_accuracy_json`

SKU 级误差的含义：
- 使用训练段数据计算动态份额
- 在验证段，用“胜出模型”的 SPU 预测值 × 预测份额，得到 SKU 预测
- 将 SKU 预测与 SKU 验证段真实销量对比，产出每个 SKU 的 WMAPE（即您关心的“spu乘权重的预测与最近真实数据的差异”）

实现位置参考：
- SKU 误差评估与落库字段：[main.py:L102-L174](file:///c:/Users/VY0814/Forecasting_Algorithm/main.py#L102-L174)
- 写库时 sku_accuracy_json 类型转换：[main.py:L245-L305](file:///c:/Users/VY0814/Forecasting_Algorithm/main.py#L245-L305)

## 2. 在数据库里查看（最直接）
建议先按 run_date + spu 查询，确认 `sku_accuracy_json` 不为空：

```sql
select
  spu,
  run_date,
  winner_algo,
  validation_wmape,
  sku_accuracy_json
from finedatalink.sales_forecast_history
where run_date = current_date
order by spu, forecast_target_date
limit 50;
```

说明：
- 表中是一周一行（forecast_target_date 为未来日期），`sku_accuracy_json` 在同一 spu 的未来行里通常是重复的（因为它对应验证段评估，不随未来周变化）。
- 若您希望一行一个 SPU（去重），可用 `distinct on (spu, run_date)` 或聚合取任一行。

## 3. 生成您要的“SPU- SKU 误差对比明细表”
目标表（示例）：
| spu | validation_wmape | sku | sku_wmape | sku_weight_in_spu | winner_algo | run_date |
|---|---:|---|---:|---:|---|---|

实现路径推荐两种：

### 方案 A：从数据库导出后，在 Python 里解析 JSON（最快落地）
1) 从库里导出字段：`spu, run_date, winner_algo, validation_wmape, sku_accuracy_json`
2) 用 pandas 展开 JSON，得到明细表

推荐直接使用项目内置脚本 [generate_accuracy_report.py](file:///c:/Users/VY0814/Forecasting_Algorithm/generate_accuracy_report.py)：

```bash
set SALES_FORECAST_DB_URL=postgresql+psycopg2://...
py generate_accuracy_report.py --run-date 2026-03-10
```

输出两份 CSV（默认目录：`D:/华熠/reports`）：
- `spu_sku_accuracy_detail_YYYYMMDD.csv`：一行一个 SKU，包含 SPU 级与 SKU 级误差
- `spu_sku_accuracy_summary_YYYYMMDD.csv`：一行一个 SPU，包含 SPU 验证误差与“SKU 加权误差”

如果只看某个 SPU：

```bash
py generate_accuracy_report.py --run-date 2026-03-10 --spu 2141
```

### 方案 B：在数据库里解析 JSON（取决于字段类型与权限）
如果您把 `sku_accuracy_json` 设为 JSON/JSONB，可用数据库 JSON 函数直接拆字段生成明细表；若为 TEXT，则需要先 cast 为 json/jsonb。

### 方案 C：直接查询数据库视图（推荐，最省事）
我已为您创建了数据库视图 `finedatalink.v_spu_sku_accuracy_detail`，直接查询该视图即可得到标准格式的明细表：

```sql
SELECT * FROM finedatalink.v_spu_sku_accuracy_detail
WHERE run_date = '2026-03-10' -- 替换为您运行预测的日期
ORDER BY spu, sku_weight_in_spu DESC;
```
若视图尚未创建，请运行脚本：
```bash
python apply_db_changes.py
```

## 4. 验收建议（两步走）
建议抽样 2 个 SPU 做快速验收：
1) SPU 级：确认 `validation_wmape` 合理（与历史波动一致）
2) SKU 级：查看 `sku_accuracy_json` 中销量权重较高（weight_in_spu 高）的 SKU，其 `wmape` 是否显著高于 SPU；若显著偏高，说明“SPU×份额”拆分对该 SPU 的 SKU 粒度不够稳定

对应 WBS 与验收清单见 [WBS.md](file:///c:/Users/VY0814/Forecasting_Algorithm/WBS.md)。
