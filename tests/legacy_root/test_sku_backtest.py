import pandas as pd
import numpy as np
import json
import traceback

# 直接复制 calculate_dynamic_shares 函数进行测试
def calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates):
    try:
        # 确保sku_sales与spu_sales_weekly的时间范围一致
        sku_sales = df_spu_idx.groupby([pd.Grouper(freq='W'), 'sku'])['sales'].sum().unstack(fill_value=0)
        # 只保留与spu_sales_weekly相同的时间范围
        sku_sales = sku_sales[sku_sales.index.isin(spu_sales_weekly.index)]
        sku_sales = sku_sales.reindex(spu_sales_weekly.index, fill_value=0)

        spu_total = sku_sales.sum(axis=1)
        hist_shares = sku_sales.div(spu_total.replace(0, np.nan), axis=0).ffill().fillna(0)

        future_shares = {}
        for sku in hist_shares.columns:
            series = hist_shares[sku]
            if len(series) >= 4:
                recent_level = series.ewm(span=8, adjust=False).mean().iloc[-1]
                try: 
                    slope, _ = np.polyfit(np.arange(4), series.iloc[-4:].values, 1)
                except Exception as e:
                    print(f"计算斜率时出错: {e}")
                    slope = 0

                future_vals, curr = [], recent_level
                for _ in range(len(future_dates)):
                    curr += slope * 0.3
                    curr = max(0.001, min(1.0, curr))
                    future_vals.append(curr); slope *= 0.8
                future_shares[sku] = future_vals
            else:
                future_shares[sku] = [series.mean() if len(series) > 0 else 0] * len(future_dates)

        future_df = pd.DataFrame(future_shares, index=future_dates)
        future_df = future_df.div(future_df.sum(axis=1), axis=0).fillna(0)

        # 计算SKU级别的回测数据
        def calculate_sku_backtest(row):
            sku_data = {}
            for sku in row.index:
                # 获取最近的SKU真实数据（最近10周）
                sku_real = sku_sales[sku].iloc[-10:].values if len(sku_sales) >= 10 else sku_sales[sku].values
                # 计算基于历史权重的预测值
                if len(hist_shares) >= 10:
                    sku_pred = (spu_sales_weekly.iloc[-10:].values * hist_shares[sku].iloc[-10:].values).flatten()
                else:
                    sku_pred = (spu_sales_weekly.values * hist_shares[sku].values).flatten()
                # 计算误差
                if len(sku_real) > 0 and len(sku_pred) > 0:
                    min_len = min(len(sku_real), len(sku_pred))
                    sku_real = sku_real[:min_len]
                    sku_pred = sku_pred[:min_len]
                    # 计算WMAPE
                    mask = sku_real != 0
                    if np.any(mask):
                        wmape = np.sum(np.abs(sku_real[mask] - sku_pred[mask])) / np.sum(np.abs(sku_real[mask]))
                    else:
                        wmape = 0
                else:
                    wmape = 0
                # 构建SKU数据字典
                sku_data[sku] = {
                    'weight': float(row[sku]),
                    'backtest': {
                        'real_values': sku_real.tolist(),
                        'pred_values': sku_pred.tolist(),
                        'wmape': float(wmape)
                    }
                }
            return json.dumps(sku_data, ensure_ascii=False)

        # ✅ 同时返回 JSON 列表（写库用，包含回测数据）和 share_df（绘图用，值为占比 0~1）
        json_list = future_df.apply(calculate_sku_backtest, axis=1).values
        return json_list, future_df
    except Exception as e:
        print(f"函数执行出错: {e}")
        traceback.print_exc()
        return None, None

# 创建测试数据
dates = pd.date_range('2023-01-01', periods=20, freq='W')
spu = '2141'

# 创建测试数据框
data = []
for date in dates:
    # 为每个SKU生成销售数据
    data.append({'date': date, 'spu': spu, 'sku': 'SKU1', 'sales': np.random.randint(10, 100)})
    data.append({'date': date, 'spu': spu, 'sku': 'SKU2', 'sales': np.random.randint(5, 50)})
    data.append({'date': date, 'spu': spu, 'sku': 'SKU3', 'sales': np.random.randint(2, 20)})

df_spu_idx = pd.DataFrame(data).set_index('date')

# 创建SPU销售数据
spu_sales_weekly = df_spu_idx.groupby(pd.Grouper(freq='W'))['sales'].sum()

# 创建未来日期
future_dates = pd.date_range(dates[-1], periods=17, freq='W')[1:]

print("测试 calculate_dynamic_shares 函数...")
print(f"历史数据日期范围: {dates[0]} 到 {dates[-1]}")
print(f"未来预测日期范围: {future_dates[0]} 到 {future_dates[-1]}")
print(f"SKU数量: {len(df_spu_idx['sku'].unique())}")
print(f"历史周数: {len(spu_sales_weekly)}")

# 调用函数
json_list, share_df = calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates)

if json_list is not None and share_df is not None:
    print("\n测试结果:")
    print(f"生成的JSON列表长度: {len(json_list)}")
    print(f"未来权重DataFrame形状: {share_df.shape}")

    # 打印第一个JSON示例
    first_json = json.loads(json_list[0])
    print("\n第一个JSON示例:")
    print(json.dumps(first_json, ensure_ascii=False, indent=2))

    # 验证回测数据是否存在
    for sku, data in first_json.items():
        if 'backtest' in data:
            backtest = data['backtest']
            print(f"\nSKU {sku} 回测数据:")
            print(f"  真实值数量: {len(backtest['real_values'])}")
            print(f"  预测值数量: {len(backtest['pred_values'])}")
            print(f"  WMAPE: {backtest['wmape']:.4f}")
else:
    print("\n测试失败: 函数返回了None")

print("\n测试完成!")