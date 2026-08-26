#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成预测结果分析报告
"""

import os
import sys
import datetime
import json

print("Generating forecast analysis report...")

# 生成预测结果分析报告
import psycopg2
import pandas as pd

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

print(f"Database URL: {DB_URL}")

try:
    # 解析连接字符串
    import urllib.parse
    parsed = urllib.parse.urlparse(DB_URL)
    host = parsed.hostname
    port = parsed.port
    database = parsed.path[1:]
    user = parsed.username
    password = parsed.password
    
    # 连接数据库
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )
    
    cursor = conn.cursor()
    
    # 获取今天的预测数据
    today = datetime.date.today()
    print(f"\nFetching forecast data for {today}...")
    
    cursor.execute("""
    SELECT 
        spu,
        forecast_target_date,
        spu_forecast_value,
        winner_algo,
        validation_wmape,
        sku_share_json,
        seasonal_factors_json,
        best_params,
        has_exog_features,
        training_weeks,
        data_end_date
    FROM finedatalink.sales_forecast_history
    WHERE run_date = %s
    ORDER BY spu, forecast_target_date
    """, (today,))
    
    results = cursor.fetchall()
    print(f"✅ Fetched {len(results)} records")
    
    if len(results) == 0:
        print("❌ No forecast data found for today")
        conn.close()
        sys.exit(1)
    
    # 转换为DataFrame
    df = pd.DataFrame(results, columns=[
        'spu', 'forecast_target_date', 'spu_forecast_value', 'winner_algo',
        'validation_wmape', 'sku_share_json', 'seasonal_factors_json',
        'best_params', 'has_exog_features', 'training_weeks', 'data_end_date'
    ])
    
    # 按SPU分组统计
    spu_stats = df.groupby('spu').agg({
        'spu_forecast_value': 'count',
        'validation_wmape': ['mean', 'min', 'max'],
        'winner_algo': lambda x: x.mode()[0] if len(x.mode()) > 0 else x.iloc[0],
        'training_weeks': 'first',
        'data_end_date': 'first'
    }).round(4)
    
    spu_stats.columns = ['record_count', 'avg_wmape', 'min_wmape', 'max_wmape', 'winner_algo', 'training_weeks', 'data_end_date']
    spu_stats = spu_stats.reset_index()
    
    # 生成HTML报告
    print("\nGenerating HTML report...")
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPU销售预测分析报告 - {today}</title>
    <style>
        body {{
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            text-align: center;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-left: 4px solid #3498db;
            padding-left: 10px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .summary-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            font-size: 14px;
            opacity: 0.9;
        }}
        .summary-card .value {{
            font-size: 28px;
            font-weight: bold;
            margin: 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background-color: white;
        }}
        th {{
            background-color: #3498db;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        tr:hover {{
            background-color: #f1f7ff;
        }}
        .wmape-low {{
            color: #27ae60;
            font-weight: bold;
        }}
        .wmape-medium {{
            color: #f39c12;
            font-weight: bold;
        }}
        .wmape-high {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .algo-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            margin-right: 5px;
        }}
        .algo-prophet {{ background-color: #9b59b6; color: white; }}
        .algo-xgboost {{ background-color: #e67e22; color: white; }}
        .algo-lightgbm {{ background-color: #2ecc71; color: white; }}
        .algo-catboost {{ background-color: #3498db; color: white; }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            color: #7f8c8d;
            font-size: 12px;
            border-top: 1px solid #ddd;
            padding-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>SPU销售预测分析报告</h1>
        <p style="text-align: center; color: #7f8c8d;">生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>执行概览</h2>
        <div class="summary">
            <div class="summary-card">
                <h3>预测日期</h3>
                <p class="value">{today}</p>
            </div>
            <div class="summary-card">
                <h3>SPU数量</h3>
                <p class="value">{len(spu_stats)}</p>
            </div>
            <div class="summary-card">
                <h3>预测记录数</h3>
                <p class="value">{len(df):,}</p>
            </div>
            <div class="summary-card">
                <h3>平均WMAPE</h3>
                <p class="value">{spu_stats['avg_wmape'].mean():.4f}</p>
            </div>
        </div>
        
        <h2>SPU预测详情</h2>
        <table>
            <thead>
                <tr>
                    <th>SPU</th>
                    <th>预测记录数</th>
                    <th>胜出算法</th>
                    <th>平均WMAPE</th>
                    <th>最小WMAPE</th>
                    <th>最大WMAPE</th>
                    <th>训练周数</th>
                    <th>数据截止日期</th>
                </tr>
            </thead>
            <tbody>
"""
    
    # 添加每个SPU的详细信息
    for _, row in spu_stats.iterrows():
        wmape_class = 'wmape-low' if row['avg_wmape'] < 0.3 else ('wmape-medium' if row['avg_wmape'] < 0.5 else 'wmape-high')
        algo_class = f"algo-{row['winner_algo'].lower()}"
        
        html_content += f"""
                <tr>
                    <td><strong>{row['spu']}</strong></td>
                    <td>{row['record_count']}</td>
                    <td><span class="algo-badge {algo_class}">{row['winner_algo']}</span></td>
                    <td class="{wmape_class}">{row['avg_wmape']:.4f}</td>
                    <td>{row['min_wmape']:.4f}</td>
                    <td>{row['max_wmape']:.4f}</td>
                    <td>{row['training_weeks']}</td>
                    <td>{row['data_end_date']}</td>
                </tr>
"""
    
    html_content += """
            </tbody>
        </table>
        
        <h2>算法性能分析</h2>
        <table>
            <thead>
                <tr>
                    <th>算法</th>
                    <th>使用次数</th>
                    <th>平均WMAPE</th>
                    <th>占比</th>
                </tr>
            </thead>
            <tbody>
"""
    
    # 算法性能统计
    algo_stats = df.groupby('winner_algo').agg({
        'spu_forecast_value': 'count',
        'validation_wmape': 'mean'
    }).round(4)
    algo_stats.columns = ['count', 'avg_wmape']
    algo_stats = algo_stats.sort_values('count', ascending=False)
    
    total_count = algo_stats['count'].sum()
    
    for algo, row in algo_stats.iterrows():
        percentage = (row['count'] / total_count) * 100
        html_content += f"""
                <tr>
                    <td><strong>{algo}</strong></td>
                    <td>{row['count']}</td>
                    <td>{row['avg_wmape']:.4f}</td>
                    <td>{percentage:.1f}%</td>
                </tr>
"""
    
    html_content += f"""
            </tbody>
        </table>
        
        <div class="footer">
            <p>SPU销售预测系统 v8.4 | 运行模式: SMART</p>
            <p>数据库: finedatalink.sales_forecast_history | 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
    
    # 保存HTML报告到桌面
    desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
    report_file = os.path.join(desktop_path, f'forecast_report_{today}.html')
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ HTML report saved to: {report_file}")
    
    cursor.close()
    conn.close()
    print("\n✅ Report generation completed successfully")
    
except Exception as e:
    print(f"❌ Report generation failed: {e}")
    import traceback
    traceback.print_exc()

print("Report generation completed.")
