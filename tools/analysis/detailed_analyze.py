import pandas as pd
import os

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'reports', 'generated'))
os.makedirs(REPORT_DIR, exist_ok=True)

print("开始详细分析数据...")

# 读取CSV文件
csv_file = 'D:/华熠/output/spu_forecast_2026-03-12.csv'
print(f"文件路径: {csv_file}")
print(f"文件存在: {os.path.exists(csv_file)}")

# 读取数据
df = pd.read_csv(csv_file)
print(f"数据条数: {len(df)}")
print(f"列名: {list(df.columns)}")

# 分析SPU数量
spu_count = df['spu'].nunique()
print(f"SPU数量: {spu_count}")

# 分析模型使用情况
model_counts = df['winner_algo'].value_counts()
print("\n模型使用情况:")
print(model_counts)

# 分析误差分布
wmape_min = df['validation_wmape'].min()
wmape_max = df['validation_wmape'].max()
wmape_mean = df['validation_wmape'].mean()
wmape_median = df['validation_wmape'].median()
print(f"\n误差分布:")
print(f"最小WMAPE: {wmape_min:.6f}")
print(f"最大WMAPE: {wmape_max:.6f}")
print(f"平均WMAPE: {wmape_mean:.6f}")
print(f"中位数WMAPE: {wmape_median:.6f}")

# 按模型分组分析
model_stats = df.groupby('winner_algo').agg({
    'spu': 'nunique',
    'validation_wmape': ['mean', 'min', 'max', 'median']
}).round(6)
print("\n按模型分组统计:")
print(model_stats)

# 分析误差分布区间
df['wmape_range'] = pd.cut(df['validation_wmape'], bins=[0, 0.05, 0.1, 0.15, 0.2, 1], labels=['优秀(<0.05)', '良好(0.05-0.1)', '一般(0.1-0.15)', '较差(0.15-0.2)', '差(>0.2)'])
range_counts = df['wmape_range'].value_counts().sort_index()
print("\n误差分布区间:")
print(range_counts)

# 生成详细的HTML报告
html_content = f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPU预测效果详细分析报告</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        h1, h2, h3 {{
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background-color: #f2f2f2;
        }}
        .summary {{
            margin: 20px 0;
            padding: 15px;
            background-color: #e8f4f8;
            border-radius: 5px;
        }}
        .model-stats {{
            margin: 20px 0;
        }}
        .error-distribution {{
            margin: 20px 0;
            padding: 15px;
            background-color: #f9f0e6;
            border-radius: 5px;
        }}
        .recommendations {{
            margin: 20px 0;
            padding: 15px;
            background-color: #f0f8f0;
            border-radius: 5px;
        }}
        .highlight {{
            font-weight: bold;
            color: #0066cc;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>SPU预测效果详细分析报告</h1>
        <p>分析时间: 2026-03-12</p>
        <p>数据来源: D:/华熠/output/spu_forecast_2026-03-12.csv</p>
    </div>
    
    <div class="container">
        <h2>1. 数据概览</h2>
        <div class="summary">
            <p><strong>总数据条数:</strong> {len(df)}</p>
            <p><strong>参与预测的SPU数量:</strong> {spu_count}</p>
            <p><strong>使用的模型数量:</strong> {len(model_counts)}</p>
        </div>
    </div>
    
    <div class="container">
        <h2>2. 预测效果分析</h2>
        <div class="error-distribution">
            <h3>误差分布统计</h3>
            <p><strong>平均误差(WMAPE):</strong> <span class="highlight">{wmape_mean:.6f}</span></p>
            <p><strong>中位数误差:</strong> {wmape_median:.6f}</p>
            <p><strong>最小误差:</strong> {wmape_min:.6f}</p>
            <p><strong>最大误差:</strong> {wmape_max:.6f}</p>
        </div>
        
        <h3>误差分布区间</h3>
        <table>
            <tr>
                <th>误差区间</th>
                <th>SPU数量</th>
                <th>占比</th>
            </tr>
'''

# 添加误差分布数据
for range_label, count in range_counts.items():
    percentage = (count / spu_count) * 100
    html_content += f'''
            <tr>
                <td>{range_label}</td>
                <td>{count}</td>
                <td>{percentage:.2f}%</td>
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
    html_content += f'''
            <tr>
                <td>{model}</td>
                <td>{count}</td>
                <td>{percentage:.2f}%</td>
                <td>{stats[('validation_wmape', 'mean')]:.6f}</td>
                <td>{stats[('validation_wmape', 'min')]:.6f}</td>
                <td>{stats[('validation_wmape', 'max')]:.6f}</td>
                <td>{stats[('validation_wmape', 'median')]:.6f}</td>
            </tr>
'''

html_content += f'''
        </table>
    </div>
    
    <div class="container">
        <h2>4. 落地建议</h2>
        <div class="recommendations">
            <h3>基于分析结果的建议</h3>
            <ul>
                <li><strong>模型优化:</strong> 根据模型表现，优先使用误差较小的模型。</li>
                <li><strong>误差监控:</strong> 建立预警机制，对误差超过0.15的SPU进行重点关注。</li>
                <li><strong>数据质量:</strong> 检查误差较大的SPU数据质量，可能存在异常值或数据缺失。</li>
                <li><strong>模型更新:</strong> 定期重新训练模型，特别是对于误差持续偏高的SPU。</li>
                <li><strong>业务结合:</strong> 结合销售策略、促销活动等因素，对预测结果进行调整。</li>
                <li><strong>性能评估:</strong> 建立定期评估机制，持续优化预测模型。</li>
            </ul>
        </div>
    </div>
    
    <div class="container">
        <h2>5. 结论</h2>
        <p>本次分析共涉及 <strong>{spu_count}</strong> 个SPU的预测数据，整体平均误差为 <span class="highlight">{wmape_mean:.6f}</span>，预测效果 <strong>{'良好' if wmape_mean < 0.1 else '一般' if wmape_mean < 0.15 else '较差'}</strong>。</p>
        <p>建议重点关注误差较大的SPU，分析原因并采取相应措施，以提高整体预测准确性。</p>
    </div>
</body>
</html>
'''

# 保存HTML报告
html_file = os.path.join(REPORT_DIR, 'spu_forecast_analysis.html')
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"\n详细分析报告已保存至: {html_file}")
print("分析完成！")
