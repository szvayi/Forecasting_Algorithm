import pandas as pd
import os

# 读取CSV文件
csv_file = 'D:/华熠/output/spu_forecast_2026-03-12.csv'
print(f"文件存在: {os.path.exists(csv_file)}")

# 读取数据，只选择需要的列
df = pd.read_csv(csv_file, usecols=['spu', 'winner_algo', 'validation_wmape'])
print(f"数据条数: {len(df)}")
print(f"列名: {list(df.columns)}")

# 分析数据
spu_count = df['spu'].nunique()
print(f"SPU数量: {spu_count}")

# 按模型分组统计
model_stats = df.groupby('winner_algo').agg({
    'spu': 'nunique',
    'validation_wmape': ['mean', 'min', 'max']
}).round(4)
print("模型统计:")
print(model_stats)

# 计算整体误差
overall_wmape = df['validation_wmape'].mean()
print(f"整体平均WMAPE: {overall_wmape:.4f}")

# 生成HTML报告
html_content = f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>预测分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1, h2 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .summary {{ background-color: #e8f4f8; padding: 15px; margin: 20px 0; }}
        .recommendations {{ background-color: #f0f8f0; padding: 15px; margin: 20px 0; }}
    </style>
</head>
<body>
    <h1>预测分析报告</h1>
    
    <div class="summary">
        <h2>1. 预测概览</h2>
        <p>参与预测的SPU数量: {spu_count}</p>
        <p>整体平均误差(WMAPE): {overall_wmape:.4f}</p>
        <p>预测数据条数: {len(df)}</p>
    </div>
    
    <h2>2. 模型使用情况</h2>
    <table>
        <tr>
            <th>模型名称</th>
            <th>使用次数</th>
            <th>平均WMAPE</th>
            <th>最小WMAPE</th>
            <th>最大WMAPE</th>
        </tr>
'''

# 添加模型数据
for model, stats in model_stats.iterrows():
    html_content += f'''
        <tr>
            <td>{model}</td>
            <td>{stats[('spu', 'nunique')]}</td>
            <td>{stats[('validation_wmape', 'mean')]}</td>
            <td>{stats[('validation_wmape', 'min')]}</td>
            <td>{stats[('validation_wmape', 'max')]}</td>
        </tr>
'''

# 添加落地建议
html_content += f'''
    </table>
    
    <div class="recommendations">
        <h2>3. 落地建议</h2>
        <ul>
            <li>模型选择: 根据模型表现，建议优先使用误差较小的模型进行预测。</li>
            <li>数据质量: 确保输入数据的准确性和完整性，特别是历史销售数据和外生变量。</li>
            <li>定期更新: 建议每周更新预测模型，以适应市场变化。</li>
            <li>监控机制: 建立预测误差监控机制，及时发现并调整预测模型。</li>
            <li>业务结合: 将预测结果与业务实际情况结合，考虑促销、季节性等因素的影响。</li>
        </ul>
    </div>
</body>
</html>
'''

# 保存HTML文件
html_file = 'forecast_analysis.html'
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"HTML报告已保存至: {html_file}")
