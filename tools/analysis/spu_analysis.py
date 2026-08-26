import pandas as pd
import os
from datetime import datetime

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'reports', 'generated'))
os.makedirs(REPORT_DIR, exist_ok=True)

print("=" * 60)
print("SPU预测效果详细分析")
print("=" * 60)

csv_file = 'D:/华熠/output/spu_forecast_2026-03-12.csv'
df = pd.read_csv(csv_file)

print(f"\n【数据基本信息】")
print(f"总数据条数: {len(df)}")
print(f"列名: {list(df.columns)}")

# 分析SPU数量
spu_count = df['spu'].nunique()
print(f"\n【SPU分析】")
print(f"参与预测的SPU数量: {spu_count}")
print(f"SPU列表: {df['spu'].unique()}")

# 每个SPU的预测次数
spu_forecast_counts = df.groupby('spu').size()
print(f"\n每个SPU的预测记录数:")
for spu, count in spu_forecast_counts.items():
    print(f"  SPU {spu}: {count} 条预测记录")

# 分析模型使用情况
print(f"\n【模型使用分析】")
model_counts = df['winner_algo'].value_counts()
print(f"模型使用分布:")
for model, count in model_counts.items():
    print(f"  {model}: {count} 次 ({count/len(df)*100:.2f}%)")

# 分析误差分布
print(f"\n【预测误差分析】")
wmape_min = df['validation_wmape'].min()
wmape_max = df['validation_wmape'].max()
wmape_mean = df['validation_wmape'].mean()
wmape_median = df['validation_wmape'].median()
wmape_std = df['validation_wmape'].std()

print(f"误差统计:")
print(f"  最小WMAPE: {wmape_min:.6f}")
print(f"  最大WMAPE: {wmape_max:.6f}")
print(f"  平均WMAPE: {wmape_mean:.6f}")
print(f"  中位数WMAPE: {wmape_median:.6f}")
print(f"  标准差: {wmape_std:.6f}")

# 误差分布区间
df['wmape_range'] = pd.cut(df['validation_wmape'], 
                           bins=[0, 0.05, 0.1, 0.15, 0.2, 1], 
                           labels=['优秀(<5%)', '良好(5-10%)', '一般(10-15%)', '较差(15-20%)', '差(>20%)'])
range_counts = df['wmape_range'].value_counts().sort_index()
print(f"\n误差分布区间:")
for range_label, count in range_counts.items():
    print(f"  {range_label}: {count} 条 ({count/len(df)*100:.2f}%)")

# 按SPU分析误差
print(f"\n【按SPU分析预测效果】")
spu_wmape = df.groupby('spu')['validation_wmape'].agg(['mean', 'min', 'max', 'count'])
for spu, stats in spu_wmape.iterrows():
    print(f"  SPU {spu}: 平均误差={stats['mean']:.6f}, 最小={stats['min']:.6f}, 最大={stats['max']:.6f}, 预测次数={int(stats['count'])}")

# 按模型分析误差
print(f"\n【按模型分析预测效果】")
model_stats = df.groupby('winner_algo').agg({
    'spu': 'nunique',
    'validation_wmape': ['mean', 'min', 'max', 'median', 'std']
}).round(6)
print(model_stats)

# 分析外生变量使用情况
print(f"\n【外生变量分析】")
exog_usage = df['has_exog_features'].value_counts()
print(f"使用外生变量的记录数: {exog_usage.get(True, 0)}")
print(f"未使用外生变量的记录数: {exog_usage.get(False, 0)}")

# 分析预测目标日期范围
print(f"\n【预测时间范围】")
print(f"预测目标日期范围: {df['forecast_target_date'].min()} 至 {df['forecast_target_date'].max()}")
print(f"数据截止日期: {df['data_end_date'].unique()}")

# 生成HTML报告
html_content = f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPU预测效果详细分析报告</title>
    <style>
        body {{
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
            line-height: 1.6;
        }}
        .container {{
            background-color: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            border-left: 4px solid #3498db;
            padding-left: 10px;
            margin-top: 25px;
        }}
        h3 {{
            color: #555;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 14px;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }}
        th {{
            background-color: #3498db;
            color: white;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .summary-box {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }}
        .summary-box p {{
            margin: 8px 0;
            font-size: 16px;
        }}
        .metric {{
            display: inline-block;
            margin: 10px 20px;
            padding: 15px 25px;
            background-color: #ecf0f1;
            border-radius: 8px;
            text-align: center;
        }}
        .metric-value {{
            font-size: 28px;
            font-weight: bold;
            color: #2980b9;
        }}
        .metric-label {{
            font-size: 14px;
            color: #7f8c8d;
        }}
        .good {{ color: #27ae60; font-weight: bold; }}
        .warning {{ color: #f39c12; font-weight: bold; }}
        .danger {{ color: #e74c3c; font-weight: bold; }}
        .recommendations {{
            background-color: #e8f6e8;
            padding: 20px;
            border-radius: 8px;
            border-left: 5px solid #27ae60;
        }}
        .recommendations li {{
            margin: 10px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>SPU预测效果详细分析报告</h1>
        <p><strong>分析时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>数据来源:</strong> {csv_file}</p>
    </div>
    
    <div class="container">
        <h2>1. 数据概览</h2>
        <div class="summary-box">
            <p><strong>总数据条数:</strong> {len(df)}</p>
            <p><strong>参与预测的SPU数量:</strong> {spu_count}</p>
            <p><strong>使用的模型数量:</strong> {len(model_counts)}</p>
            <p><strong>预测时间范围:</strong> {df['forecast_target_date'].min()} 至 {df['forecast_target_date'].max()}</p>
        </div>
        
        <h3>SPU预测记录分布</h3>
        <table>
            <tr>
                <th>SPU编号</th>
                <th>预测记录数</th>
                <th>平均WMAPE</th>
                <th>最小WMAPE</th>
                <th>最大WMAPE</th>
            </tr>
'''

# 添加SPU数据
for spu, stats in spu_wmape.iterrows():
    avg_class = 'good' if stats['mean'] < 0.1 else 'warning' if stats['mean'] < 0.15 else 'danger'
    html_content += f'''
            <tr>
                <td>{spu}</td>
                <td>{int(stats['count'])}</td>
                <td class="{avg_class}">{stats['mean']:.6f}</td>
                <td>{stats['min']:.6f}</td>
                <td>{stats['max']:.6f}</td>
            </tr>
'''

html_content += f'''
        </table>
    </div>
    
    <div class="container">
        <h2>2. 预测效果分析</h2>
        
        <div style="text-align: center; margin: 30px 0;">
            <div class="metric">
                <div class="metric-value">{wmape_mean:.4f}</div>
                <div class="metric-label">平均WMAPE</div>
            </div>
            <div class="metric">
                <div class="metric-value">{wmape_median:.4f}</div>
                <div class="metric-label">中位数WMAPE</div>
            </div>
            <div class="metric">
                <div class="metric-value">{wmape_min:.4f}</div>
                <div class="metric-label">最小WMAPE</div>
            </div>
            <div class="metric">
                <div class="metric-value">{wmape_max:.4f}</div>
                <div class="metric-label">最大WMAPE</div>
            </div>
        </div>
        
        <h3>误差分布区间</h3>
        <table>
            <tr>
                <th>误差区间</th>
                <th>记录数</th>
                <th>占比</th>
                <th>评价</th>
            </tr>
'''

# 添加误差分布数据
evaluations = {
    '优秀(<5%)': '预测效果优秀，可直接应用',
    '良好(5-10%)': '预测效果良好，可正常使用',
    '一般(10-15%)': '预测效果一般，需关注',
    '较差(15-20%)': '预测效果较差，需优化',
    '差(>20%)': '预测效果差，需重点优化'
}

for range_label, count in range_counts.items():
    percentage = (count / len(df)) * 100
    eval_text = evaluations.get(str(range_label), '')
    html_content += f'''
            <tr>
                <td>{range_label}</td>
                <td>{count}</td>
                <td>{percentage:.2f}%</td>
                <td>{eval_text}</td>
            </tr>
'''

html_content += f'''
        </table>
    </div>
    
    <div class="container">
        <h2>3. 模型使用情况</h2>
        
        <h3>模型使用分布</h3>
        <table>
            <tr>
                <th>模型名称</th>
                <th>使用次数</th>
                <th>占比</th>
                <th>平均WMAPE</th>
                <th>最小WMAPE</th>
                <th>最大WMAPE</th>
                <th>中位数WMAPE</th>
            </tr>
'''

# 添加模型统计数据
for model, stats in model_stats.iterrows():
    count = stats[('spu', 'nunique')]
    percentage = (count / spu_count) * 100
    avg_wmape = stats[('validation_wmape', 'mean')]
    avg_class = 'good' if avg_wmape < 0.1 else 'warning' if avg_wmape < 0.15 else 'danger'
    html_content += f'''
            <tr>
                <td>{model}</td>
                <td>{count}</td>
                <td>{percentage:.2f}%</td>
                <td class="{avg_class}">{avg_wmape:.6f}</td>
                <td>{stats[('validation_wmape', 'min')]:.6f}</td>
                <td>{stats[('validation_wmape', 'max')]:.6f}</td>
                <td>{stats[('validation_wmape', 'median')]:.6f}</td>
            </tr>
'''

html_content += f'''
        </table>
    </div>
    
    <div class="container">
        <h2>4. 外生变量分析</h2>
        <p><strong>使用外生变量的记录数:</strong> {exog_usage.get(True, 0)} ({exog_usage.get(True, 0)/len(df)*100:.2f}%)</p>
        <p><strong>未使用外生变量的记录数:</strong> {exog_usage.get(False, 0)} ({exog_usage.get(False, 0)/len(df)*100:.2f}%)</p>
        <p><strong>外生变量类型:</strong> {df[df['has_exog_features']==True]['exog_columns'].iloc[0] if exog_usage.get(True, 0) > 0 else '无'}</p>
    </div>
    
    <div class="container">
        <h2>5. 落地建议</h2>
        <div class="recommendations">
            <h3>基于分析结果的建议</h3>
            <ul>
                <li><strong>模型选择:</strong> 当前主要使用 <strong>{model_counts.index[0]}</strong> 模型，平均误差为 <strong>{wmape_mean:.4f}</strong>，整体预测效果{'优秀' if wmape_mean < 0.1 else '良好' if wmape_mean < 0.15 else '一般'}。</li>
                <li><strong>误差监控:</strong> 建议建立预警机制，对误差超过15%的SPU进行重点关注和分析。</li>
                <li><strong>数据质量:</strong> 检查误差较大的SPU数据质量，可能存在异常值、数据缺失或销售波动大的情况。</li>
                <li><strong>模型优化:</strong> 对于误差较大的SPU，建议：
                    <ul>
                        <li>增加历史数据量</li>
                        <li>引入更多外生变量（如促销、节假日等）</li>
                        <li>尝试其他预测模型</li>
                    </ul>
                </li>
                <li><strong>定期更新:</strong> 建议每周更新预测模型，以适应市场变化和销售趋势。</li>
                <li><strong>业务结合:</strong> 将预测结果与业务实际情况结合，考虑促销活动、季节性因素、库存策略等影响。</li>
                <li><strong>性能评估:</strong> 建立定期评估机制，持续跟踪预测准确性，形成闭环优化。</li>
            </ul>
        </div>
    </div>
    
    <div class="container">
        <h2>6. 结论</h2>
        <p>本次分析共涉及 <strong>{spu_count}</strong> 个SPU的预测数据，总计 <strong>{len(df)}</strong> 条预测记录。</p>
        <p>整体平均误差为 <strong>{wmape_mean:.4f}</strong>，预测效果 <strong>{'优秀' if wmape_mean < 0.1 else '良好' if wmape_mean < 0.15 else '一般'}</strong>。</p>
        <p>主要使用模型: <strong>{model_counts.index[0]}</strong>，该模型在当前数据集上表现{'稳定' if wmape_std < 0.05 else '有一定波动'}。</p>
        <p>建议重点关注误差较大的SPU，分析原因并采取相应措施，以提高整体预测准确性。</p>
    </div>
</body>
</html>
'''

# 保存HTML报告
html_file = os.path.join(REPORT_DIR, 'spu_forecast_analysis.html')
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"\n{'=' * 60}")
print(f"详细分析报告已保存至: {html_file}")
print(f"{'=' * 60}")
