import pandas as pd
import os

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'reports', 'generated'))
os.makedirs(REPORT_DIR, exist_ok=True)

# 读取CSV文件
csv_file = 'D:/华熠/output/spu_forecast_2026-03-12.csv'

# 读取数据
df = pd.read_csv(csv_file)

# 分析数据
spu_count = df['spu'].nunique()
model_stats = df.groupby('winner_algo').agg({
    'spu': 'nunique',
    'validation_wmape': ['mean', 'min', 'max']
}).round(4)
overall_wmape = df['validation_wmape'].mean()

# 生成HTML报告
html = f'''
<!DOCTYPE html>
<html>
<head>
    <title>预测分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .section {{ margin: 20px 0; padding: 15px; background-color: #f9f9f9; }}
    </style>
</head>
<body>
    <h1>预测分析报告</h1>
    
    <div class="section">
        <h2>1. 预测概览</h2>
        <p>参与预测的SPU数量: {spu_count}</p>
        <p>整体平均误差(WMAPE): {overall_wmape:.4f}</p>
        <p>预测数据条数: {len(df)}</p>
    </div>
    
    <div class="section">
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
    html += f'''
            <tr>
                <td>{model}</td>
                <td>{stats[('spu', 'nunique')]}</td>
                <td>{stats[('validation_wmape', 'mean')]}</td>
                <td>{stats[('validation_wmape', 'min')]}</td>
                <td>{stats[('validation_wmape', 'max')]}</td>
            </tr>
'''

# 添加落地建议
html += f'''
        </table>
    </div>
    
    <div class="section">
        <h2>3. 落地建议</h2>
        <ul>
            <li>模型选择: 根据模型表现，优先使用误差较小的模型</li>
            <li>数据质量: 确保输入数据的准确性和完整性</li>
            <li>定期更新: 建议每周更新预测模型</li>
            <li>监控机制: 建立预测误差监控机制</li>
            <li>业务结合: 将预测结果与业务实际情况结合</li>
        </ul>
    </div>
</body>
</html>
'''

# 保存HTML文件
with open(os.path.join(REPORT_DIR, 'forecast_analysis.html'), 'w', encoding='utf-8') as f:
    f.write(html)

print('分析完成！HTML报告已生成。')
