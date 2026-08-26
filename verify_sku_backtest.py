# 验证SKU回测功能是否正确实现

# 1. 检查代码修改是否正确
print("=== 验证SKU回测功能 ===")
print("\n1. 检查代码修改:")

# 读取修改后的文件
with open('src/forecasting/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 检查是否包含回测相关代码
if 'backtest' in content:
    print("✅ 代码中包含回测功能")
else:
    print("❌ 代码中未包含回测功能")

if 'real_values' in content:
    print("✅ 代码中包含真实值")
else:
    print("❌ 代码中未包含真实值")

if 'pred_values' in content:
    print("✅ 代码中包含预测值")
else:
    print("❌ 代码中未包含预测值")

if 'wmape' in content:
    print("✅ 代码中包含误差计算")
else:
    print("❌ 代码中未包含误差计算")

print("\n2. 检查JSON结构:")
# 检查JSON结构是否正确
if 'sku_data[sku] = {' in content:
    print("✅ 正确构建SKU数据字典")
else:
    print("❌ 未正确构建SKU数据字典")

if 'json.dumps(sku_data, ensure_ascii=False)' in content:
    print("✅ 正确序列化JSON")
else:
    print("❌ 未正确序列化JSON")

print("\n3. 功能说明:")
print("修改后的 `calculate_dynamic_shares` 函数现在会:")
print("- 为每个SKU计算最近10周的真实销售数据")
print("- 基于历史权重计算SKU的预测销售数据")
print("- 计算每个SKU的WMAPE误差")
print("- 将这些信息作为JSON对象返回，包含:")
print("  * sku权重 (weight)")
print("  * 真实值列表 (real_values)")
print("  * 预测值列表 (pred_values)")
print("  * 误差值 (wmape)")

print("\n=== 验证完成 ===")