import pandas as pd
import numpy as np
import json
import traceback

# 读取数据
try:
    print("正在读取数据...")
    df = pd.read_csv('D:/华熠/output/spu_forecast_2026-03-12.csv')
    print(f"数据读取成功，共 {len(df)} 条记录")
    
    # 分析数据
    total_records = len(df)
    spu_count = df['spu'].nunique()
    spu_list = df['spu'].unique()
    
    print(f"SPU数量: {spu_count}")
    print(f"所有SPU: {spu_list.tolist()}")
    
    # 每个SPU的详细分析
    all_spu_data = []
    for spu in spu_list:
        spu_data = df[df['spu'] == spu]
        
        # 按日期排序
        spu_data_sorted = spu_data.sort_values('forecast_date')
        
        # 计算4周和8周的增长下降
        forecast_values = spu_data_sorted['forecast_value'].tolist()
        
        # 4周趋势（如果有足够数据）
        four_week_trend = "数据不足"
        if len(forecast_values) >= 4:
            start_4w = forecast_values[0]
            end_4w = forecast_values[3]
            if end_4w > start_4w:
                four_week_trend = f"增长 {((end_4w - start_4w) / start_4w * 100):.2f}%"
            elif end_4w < start_4w:
                four_week_trend = f"下降 {((start_4w - end_4w) / start_4w * 100):.2f}%"
            else:
                four_week_trend = "持平"
        
        # 8周趋势（如果有足够数据）
        eight_week_trend = "数据不足"
        if len(forecast_values) >= 8:
            start_8w = forecast_values[0]
            end_8w = forecast_values[7]
            if end_8w > start_8w:
                eight_week_trend = f"增长 {((end_8w - start_8w) / start_8w * 100):.2f}%"
            elif end_8w < start_8w:
                eight_week_trend = f"下降 {((start_8w - end_8w) / start_8w * 100):.2f}%"
            else:
                eight_week_trend = "持平"
        
        # 计算WMAPE统计
        mean_wmape = float(spu_data['wmape'].mean())
        min_wmape = float(spu_data['wmape'].min())
        max_wmape = float(spu_data['wmape'].max())
        
        # 确定性能评价
        if mean_wmape < 5:
            performance = "优秀"
        elif mean_wmape < 10:
            performance = "良好"
        elif mean_wmape < 15:
            performance = "一般"
        else:
            performance = "较差"
        
        # 模型信息
        models = list(spu_data['winner_algo'].unique())
        
        # 构建SPU数据
        spu_info = {
            'spu': spu,
            'records': len(spu_data),
            'mean_wmape': mean_wmape,
            'min_wmape': min_wmape,
            'max_wmape': max_wmape,
            'performance': performance,
            'models': models,
            'four_week_trend': four_week_trend,
            'eight_week_trend': eight_week_trend,
            'forecast_values': forecast_values[:8]  # 前8周的预测值
        }
        
        all_spu_data.append(spu_info)
    
    # 整体统计
    wmape_stats = {
        'mean': float(df['wmape'].mean()),
        'min': float(df['wmape'].min()),
        'max': float(df['wmape'].max())
    }
    
    # 模型使用情况
    model_counts = df['winner_algo'].value_counts().to_dict()
    
    # 准备数据用于HTML报告
    analysis_data = {
        'total_records': total_records,
        'spu_count': spu_count,
        'spu_list': spu_list.tolist(),
        'all_spu_data': all_spu_data,
        'wmape_stats': wmape_stats,
        'model_counts': model_counts
    }
    
    # 保存分析数据
    with open('all_spu_analysis_data.json', 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=2)
    print("\n分析数据已保存到 all_spu_analysis_data.json")
    
    # 打印前几个SPU的信息
    print("\n前5个SPU的详细信息:")
    for spu_info in all_spu_data[:5]:
        print(f"SPU {spu_info['spu']}: 平均WMAPE={spu_info['mean_wmape']:.4f}, 4周趋势={spu_info['four_week_trend']}, 8周趋势={spu_info['eight_week_trend']}")
    
except Exception as e:
    print(f"错误: {e}")
    traceback.print_exc()