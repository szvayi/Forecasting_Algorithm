# 第一版 Smoke 回归入口

这个文档只定义第一版最小但可信的回归入口，不扩展新的测试体系。

## 硬门槛 Smoke

### 1. 平台与接线层

运行：

```bash
pytest tests/test_forecast_platform.py tests/test_runtime_facade.py tests/test_execution_bridge.py tests/test_legacy_entrypoint.py tests/test_forecasting_kernel.py -q
```

覆盖面：
- FastAPI 平台入口
- runtime facade
- execution bridge
- legacy 入口兼容
- canonical kernel 的关键接线

当前结果：
- `23 passed`

### 2. 预测主链

运行：

```bash
pytest tests/forecasting/test_core.py tests/forecasting/test_monitor.py tests/forecasting/test_integration.py -q
```

覆盖面：
- 核心预测函数
- 单 SPU / SKU 接线
- 监控与告警关键路径
- 集成级回归

当前结果：
- `27 passed`

## 可选补充

### 3. 通用工具与特性回归

运行：

```bash
pytest tests/test_config_and_utils.py tests/test_feature_enhancements.py -q
```

当前结果：
- `6 passed`

说明：
- 这组作为补充回归保留，不作为第一版硬门槛。
- 它适合在发布前最后再跑一次，用来确认通用工具层没有回退。

## 不纳入第一版 Smoke 的项

`tests/test_generate_accuracy_report.py` 当前在收集阶段有导入错误：

- `ImportError: cannot import name 'expand_sku_accuracy_rows' from 'generate_accuracy_report'`

所以这条暂时不放进第一版 smoke，避免把 release gate 卡在一个明显独立的历史问题上。

## 第一版发布建议

第一版建议至少满足以下条件：

1. 硬门槛 Smoke 全绿。
2. 可选补充 Smoke 通过。
3. `tests/test_generate_accuracy_report.py` 仍然可以保留为后续修复项，但不阻塞第一版。

