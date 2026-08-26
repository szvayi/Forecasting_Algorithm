import pandas as pd
import numpy as np
import json

# 读取数据
df = pd.read_csv('D:/华熠/output/spu_forecast_2026-03-12.csv')

# 分析数据
total_records = len(df)
spu_count = df['spu'].nunique()
spu_list = df['spu'].unique()

# 每个SPU的预测记录数
spu_forecast_counts = df['spu'].value_counts().to_dict()

# 模型使用情况
model_counts = df['winner_algo'].value_counts().to_dict()

# 整体WMAPE统计
wmape_stats = {
    'mean': float(df['wmape'].mean()),
    'min': float(df['wmape'].min()),
    'max': float(df['wmape'].max())
}

# 每个SPU的WMAPE统计
spu_wmape_stats = {}
for spu in spu_list:
    spu_data = df[df['spu'] == spu]
    spu_wmape_stats[spu] = {
        'mean_wmape': float(spu_data['wmape'].mean()),
        'min_wmape': float(spu_data['wmape'].min()),
        'max_wmape': float(spu_data['wmape'].max()),
        'records': len(spu_data),
        'models': list(spu_data['winner_algo'].unique())
    }

# 准备数据用于HTML报告
analysis_data = {
    'total_records': total_records,
    'spu_count': spu_count,
    'spu_list': spu_list.tolist(),
    'spu_forecast_counts': spu_forecast_counts,
    'model_counts': model_counts,
    'wmape_stats': wmape_stats,
    'spu_wmape_stats': spu_wmape_stats
}

# 保存分析数据
with open('analysis_data.json', 'w', encoding='utf-8') as f:
    json.dump(analysis_data, f, ensure_ascii=False, indent=2)

print(f"分析完成！")
print(f"总记录数: {total_records}")
print(f"SPU数量: {spu_count}")
print(f"SPU列表: {spu_list.tolist()}")
print(f"模型使用情况: {model_counts}")
print(f"WMAPE统计: {wmape_stats}")