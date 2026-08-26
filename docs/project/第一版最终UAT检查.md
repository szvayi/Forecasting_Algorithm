# 第一版最终 UAT / 发布前检查

## 检查范围
- 平台入口可用性
- 关键 API / 运行链
- 第一版 smoke 回归
- 已知独立风险点

## 检查结果
- 平台与接线层：`23 passed`
- 预测主链：`27 passed`
- 通用工具与特性回归：`6 passed`
- `tests/test_generate_accuracy_report.py`：收集阶段仍报 `ImportError: cannot import name 'expand_sku_accuracy_rows'`

## 发布判断
- 第一版内部发布：可通过
- 第一版对外最终版：暂不建议

## 结论
- 主链与 smoke 已满足第一版内部交付条件
- 唯一明确的独立风险是 `tests/test_generate_accuracy_report.py`，它不阻塞第一版内部发布，但会阻塞“全绿”口径
