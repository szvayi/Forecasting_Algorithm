#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SPU回测准确率分析报告生成器
分析模型在验证期间的预测结果
"""
import sys
sys.path.insert(0, 'c:\\Users\\VY0814\\Forecasting_Algorithm')

import os
import pandas as pd
import numpy as np
import json
from datetime import datetime
import glob

# 34个目标SPU列表
TARGET_SPUS = {
    '2141', '2062', '2029', '2046', '2026', '3022', '1930', '2214',
    '2033', '2038', '2208', '2012', '3050', '2176', '3033', '2192',
    '2213', '3063', '2224', '3058', '2073', '3013', '2165', '3084',
    '1976', '2197', '1476', '1533', '887', '1577', '1750', '1512',
    '1657', '1983', '1318'
}

def get_backtest_data():
    """从日志文件中提取回测数据"""
    print("🔄 正在从日志文件中提取回测数据...")
    
    # 查找最新的日志文件
    log_files = glob.glob('run_forecast_*.log')
    if not log_files:
        print("❌ 未找到日志文件")
        return []
    
    # 按修改时间排序，取最新的
    log_files.sort(key=os.path.getmtime, reverse=True)
    latest_log = log_files[0]
    print(f"📄 正在分析日志文件: {latest_log}")
    
    backtest_data = []
    spu_status = {}
    
    try:
        with open(latest_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_spu = None
        model_results = []
        spu_statuses = []
        
        for line in lines:
            line = line.strip()
            
            # 识别SPU开始 (支持中文和英文格式)
            if '处理 SPU:' in line or '澶勭悊 SPU:' in line:
                if current_spu and model_results:
                    # 保存之前的SPU数据
                    backtest_data.append({
                        'spu': current_spu,
                        'models': model_results,
                        'status': '成功'
                    })
                    spu_status[current_spu] = '成功'
                # 提取SPU编号
                if '处理 SPU:' in line:
                    spu = line.split('处理 SPU:')[1].strip()
                else:
                    spu = line.split('澶勭悊 SPU:')[1].strip()
                current_spu = spu
                model_results = []
            
            # 识别模型结果
            elif 'WMAPE:' in line and ('Prophet' in line or 'XGBoost' in line or 'LightGBM' in line):
                # 解析模型名称和WMAPE
                parts = line.split('(')
                model_name = parts[0].strip()
                wmape_part = parts[1].split(')')[0]
                if 'WMAPE:' in wmape_part:
                    wmape_str = wmape_part.split('WMAPE:')[1].strip()
                    # 移除百分号并转换为浮点数
                    wmape = float(wmape_str.replace('%', '')) / 100
                    model_results.append({
                        'name': model_name,
                        'wmape': wmape
                    })
            
            # 识别错误信息
            elif current_spu and '错误:' in line:
                error_msg = line.split('错误:')[1].strip()
                backtest_data.append({
                    'spu': current_spu,
                    'models': [],
                    'status': f'失败: {error_msg}'
                })
                spu_status[current_spu] = f'失败: {error_msg}'
                current_spu = None
                model_results = []
            
            # 识别数据不足信息
            elif current_spu and '数据不足' in line:
                backtest_data.append({
                    'spu': current_spu,
                    'models': [],
                    'status': '数据不足'
                })
                spu_status[current_spu] = '数据不足'
                current_spu = None
                model_results = []
        
        # 保存最后一个SPU的数据
        if current_spu and model_results:
            backtest_data.append({
                'spu': current_spu,
                'models': model_results,
                'status': '成功'
            })
            spu_status[current_spu] = '成功'
        
        # 处理未出现在日志中的SPU（可能是数据不足）
        for spu in TARGET_SPUS:
            if spu not in spu_status:
                backtest_data.append({
                    'spu': spu,
                    'models': [],
                    'status': '数据不足'
                })
                spu_status[spu] = '数据不足'
        
        print(f"✅ 成功提取 {len(backtest_data)} 个SPU的回测数据")
        return backtest_data
        
    except Exception as e:
        print(f"❌ 解析日志文件失败: {e}")
        return []

def calculate_wmape(y_true, y_pred):
    """计算加权平均绝对百分比误差"""
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    mask = y_true != 0
    if not np.any(mask):
        return 0.0
    return np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask]))

def generate_html_report(backtest_data, output_path):
    """生成HTML报告"""
    print("📊 正在生成HTML报告...")
    
    # 准备数据
    spu_accuracy = []
    model_performance = {}
    status_counts = {'成功': 0, '失败': 0, '数据不足': 0}
    
    for data in backtest_data:
        spu = data['spu']
        models = data['models']
        status = data['status']
        
        # 统计状态
        if status == '成功':
            status_counts['成功'] += 1
        elif status.startswith('失败'):
            status_counts['失败'] += 1
        else:
            status_counts['数据不足'] += 1
        
        if models:
            # 找到最佳模型
            best_model = min(models, key=lambda x: x['wmape'])
            spu_accuracy.append({
                'spu': spu,
                'best_model': best_model['name'],
                'wmape': best_model['wmape'],
                'status': status
            })
            
            # 统计模型性能
            for model in models:
                model_name = model['name']
                if model_name not in model_performance:
                    model_performance[model_name] = []
                model_performance[model_name].append(model['wmape'])
        else:
            spu_accuracy.append({
                'spu': spu,
                'best_model': '-',
                'wmape': None,
                'status': status
            })
    
    # 转换为DataFrame
    spu_accuracy_df = pd.DataFrame(spu_accuracy)
    
    # 计算总体统计（只考虑成功的SPU）
    successful_spus = spu_accuracy_df[spu_accuracy_df['status'] == '成功']
    if not successful_spus.empty:
        overall_avg_wmape = successful_spus['wmape'].mean()
        overall_median_wmape = successful_spus['wmape'].median()
        overall_min_wmape = successful_spus['wmape'].min()
        overall_max_wmape = successful_spus['wmape'].max()
    else:
        overall_avg_wmape = 0
        overall_median_wmape = 0
        overall_min_wmape = 0
        overall_max_wmape = 0
    
    # 计算模型平均性能
    model_stats = []
    for model_name, wmapes in model_performance.items():
        if wmapes:
            model_stats.append({
                'model': model_name,
                'avg_wmape': np.mean(wmapes),
                'count': len(wmapes)
            })
    model_stats_df = pd.DataFrame(model_stats)
    
    # 按准确率排序
    sorted_accuracy = spu_accuracy_df.sort_values('wmape', ascending=True)
    
    # 生成HTML内容
    html_content = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPU回测准确率分析报告</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        h1, h2, h3 {
            color: #2c3e50;
            margin-bottom: 20px;
        }
        h1 {
            font-size: 28px;
            text-align: center;
            margin-bottom: 40px;
            color: #3498db;
        }
        .summary {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .summary-item {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }
        .summary-item h3 {
            font-size: 16px;
            color: #666;
            margin-bottom: 10px;
        }
        .summary-item .value {
            font-size: 24px;
            font-weight: bold;
            color: #3498db;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            margin-top: 20px;
        }
        .status-item {
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }
        .status-item.success {
            background: #d4edda;
            color: #155724;
        }
        .status-item.failed {
            background: #f8d7da;
            color: #721c24;
        }
        .status-item.insufficient {
            background: #fff3cd;
            color: #856404;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            overflow: hidden;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }
        th {
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .error-bar {
            height: 8px;
            background: linear-gradient(to right, #4CAF50, #FFC107, #F44336);
            border-radius: 4px;
            margin-top: 5px;
        }
        .footer {
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            background: #2c3e50;
            color: white;
            border-radius: 8px;
        }
        .status-badge {
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-badge.success {
            background: #d4edda;
            color: #155724;
        }
        .status-badge.failed {
            background: #f8d7da;
            color: #721c24;
        }
        .status-badge.insufficient {
            background: #fff3cd;
            color: #856404;
        }
        .model-stats {
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>SPU回测准确率分析报告</h1>
        
        <div class="summary">
            <h2>总体概览</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <h3>目标SPU总数</h3>
                    <div class="value">''' + f"{len(TARGET_SPUS)}" + '''</div>
                </div>
                <div class="summary-item">
                    <h3>成功处理SPU</h3>
                    <div class="value">''' + f"{status_counts['成功']}" + '''</div>
                </div>
                <div class="summary-item">
                    <h3>失败SPU</h3>
                    <div class="value">''' + f"{status_counts['失败']}" + '''</div>
                </div>
                <div class="summary-item">
                    <h3>数据不足SPU</h3>
                    <div class="value">''' + f"{status_counts['数据不足']}" + '''</div>
                </div>
                <div class="summary-item">
                    <h3>平均WMAPE</h3>
                    <div class="value">''' + f"{overall_avg_wmape:.2%}" + '''</div>
                </div>
                <div class="summary-item">
                    <h3>生成时间</h3>
                    <div class="value">''' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '''</div>
                </div>
            </div>
            
            <h3>SPU状态分布</h3>
            <div class="status-grid">
                <div class="status-item success">
                    <h4>成功</h4>
                    <div style="font-size: 24px; font-weight: bold;">''' + f"{status_counts['成功']}" + '''</div>
                </div>
                <div class="status-item failed">
                    <h4>失败</h4>
                    <div style="font-size: 24px; font-weight: bold;">''' + f"{status_counts['失败']}" + '''</div>
                </div>
                <div class="status-item insufficient">
                    <h4>数据不足</h4>
                    <div style="font-size: 24px; font-weight: bold;">''' + f"{status_counts['数据不足']}" + '''</div>
                </div>
            </div>
        </div>
        
        <h2>SPU回测准确率排行</h2>
        <table>
            <thead>
                <tr>
                    <th>排名</th>
                    <th>SPU</th>
                    <th>最佳模型</th>
                    <th>WMAPE</th>
                    <th>状态</th>
                    <th>误差分布</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    # 添加SPU准确率数据
    rank = 1
    for _, row in sorted_accuracy.iterrows():
        wmape = row['wmape']
        status = row['status']
        
        if status == '成功':
            status_class = 'success'
        elif status.startswith('失败'):
            status_class = 'failed'
        else:
            status_class = 'insufficient'
        
        error_bar = ''
        if wmape is not None:
            width = min(wmape * 500, 100)
            error_bar = '''
                        <div class="error-bar" style="width: ''' + str(width) + '''%"></div>
            '''
        
        # 使用字符串拼接避免f-string格式错误
        wmape_str = f"{wmape:.2%}" if wmape is not None else "-"
        rank_str = str(rank) if status == '成功' else "-"
        
        html_content += '''
                <tr>
                    <td>''' + rank_str + '''</td>
                    <td>''' + row['spu'] + '''</td>
                    <td>''' + row['best_model'] + '''</td>
                    <td>''' + wmape_str + '''</td>
                    <td><span class="status-badge ''' + status_class + '''">''' + status + '''</span></td>
                    <td>''' + error_bar + '''</td>
                </tr>
        '''
        if status == '成功':
            rank += 1
    
    html_content += '''
            </tbody>
        </table>
        
        <h2>模型性能统计</h2>
        <table class="model-stats">
            <thead>
                <tr>
                    <th>模型</th>
                    <th>平均WMAPE</th>
                    <th>使用次数</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    # 添加模型性能数据
    for _, row in model_stats_df.sort_values('avg_wmape').iterrows():
        html_content += f'''
                <tr>
                    <td>{row['model']}</td>
                    <td>{row['avg_wmape']:.2%}</td>
                    <td>{row['count']}</td>
                </tr>
    '''
    
    # 使用字符串拼接避免f-string格式错误
    report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    html_content += '''
            </tbody>
        </table>
        
        <div class="footer">
            <p>报告生成时间: ''' + report_time + '''</p>
            <p>数据来源: 销售预测系统 v8.5 回测结果</p>
            <p>目标SPU数量: 34个</p>
        </div>
    </div>
</body>
</html>
    '''
    
    # 保存HTML文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ 报告已保存至: {output_path}")

def main():
    """主函数"""
    print("=" * 70)
    print("📈 SPU回测准确率分析报告生成器")
    print("=" * 70)
    
    # 获取回测数据
    backtest_data = get_backtest_data()
    
    if not backtest_data:
        print("❌ 未找到回测数据")
        return
    
    # 生成报告
    output_file = f'spu_backtest_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    
    generate_html_report(backtest_data, output_file)
    
    print("=" * 70)
    print("✅ 报告生成完成！")
    print(f"📄 报告位置: {output_file}")
    print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 生成报告失败: {e}")
        import traceback
        traceback.print_exc()
