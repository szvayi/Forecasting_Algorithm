import pandas as pd
import os
from datetime import datetime
import sys

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'reports', 'generated'))
os.makedirs(REPORT_DIR, exist_ok=True)

# 读取CSV文件
csv_file = 'D:/华熠/output/spu_forecast_2026-03-12.csv'
print(f"正在读取文件: {csv_file}")
print(f"文件是否存在: {os.path.exists(csv_file)}")
print(f"Python版本: {sys.version}")
print(f"Pandas版本: {pd.__version__}")

try:
    print("开始读取CSV文件...")
    df = pd.read_csv(csv_file)
    print(f"读取成功，数据条数: {len(df)}")
    print(f"列名: {list(df.columns)}")
    print(f"前5行数据:")
    print(df.head())
    
    # 分析数据
    spu_count = df['spu'].nunique()
    model_stats = df.groupby('winner_algo').agg({
        'spu': 'nunique',
        'validation_wmape': ['mean', 'min', 'max']
    }).round(4)
    
    # 计算整体预测表现
    overall_wmape = df['validation_wmape'].mean()
    
    # 生成HTML报告
    html_content = f'''
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>预测分析报告</title>
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
            }}
            h1, h2 {{
                color: #333;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
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
            .recommendations {{  
                margin: 20px 0;
                padding: 15px;
                background-color: #f0f8f0;
                border-radius: 5px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>预测分析报告</h1>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            
            <div class="summary">
                <h2>1. 预测概览</h2>
                <p><strong>参与预测的SPU数量:</strong> {spu_count}</p>
                <p><strong>整体平均误差(WMAPE):</strong> {overall_wmape:.4f}</p>
                <p><strong>预测数据条数:</strong> {len(df)}</p>
            </div>
            
            <div class="model-stats">
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
    
    # 添加模型统计数据
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
            </div>
            
            <div class="recommendations">
                <h2>3. 落地建议</h2>
                <ul>
                    <li><strong>模型选择:</strong> 根据模型表现，建议优先使用误差较小的模型进行预测。</li>
                    <li><strong>数据质量:</strong> 确保输入数据的准确性和完整性，特别是历史销售数据和外生变量。</li>
                    <li><strong>定期更新:</strong> 建议每周更新预测模型，以适应市场变化。</li>
                    <li><strong>监控机制:</strong> 建立预测误差监控机制，及时发现并调整预测模型。</li>
                    <li><strong>业务结合:</strong> 将预测结果与业务实际情况结合，考虑促销、季节性等因素的影响。</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    '''
    
    # 保存HTML文件
    html_file = os.path.join(REPORT_DIR, 'forecast_analysis.html')
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"分析完成！HTML报告已保存至: {html_file}")
    print(f"参与预测的SPU数量: {spu_count}")
    print(f"整体平均误差(WMAPE): {overall_wmape:.4f}")
    print("模型使用情况:")
    print(model_stats)
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
