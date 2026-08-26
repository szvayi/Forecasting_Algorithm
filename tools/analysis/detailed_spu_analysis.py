import pandas as pd
import numpy as np
import traceback

# 读取数据
try:
    print("正在读取数据...")
    df = pd.read_csv('D:/华熠/output/spu_forecast_2026-03-12.csv')
    print(f"数据读取成功，共 {len(df)} 条记录")
    
    # 检查数据结构
    print(f"\n列名: {df.columns.tolist()}")
    print(f"\n数据类型:")
    print(df.dtypes)
    
    # 分析SPU数量
    if 'spu' in df.columns:
        spu_count = df['spu'].nunique()
        print(f"\nSPU数量: {spu_count}")
        
        # 显示前20个SPU
        spu_list = df['spu'].unique()
        print(f"\n前20个SPU: {spu_list[:20]}")
        
        # 分析每个SPU的预测记录数
        spu_counts = df['spu'].value_counts()
        print(f"\n每个SPU的预测记录数:")
        for spu, count in spu_counts.items():
            print(f"  SPU {spu}: {count} 条")
    else:
        print("\n错误: 数据中没有 'spu' 列")
        print("列名列表:", df.columns.tolist())
    
    # 分析模型使用情况
    if 'winner_algo' in df.columns:
        model_counts = df['winner_algo'].value_counts()
        print(f"\n模型使用情况:")
        for model, count in model_counts.items():
            print(f"  {model}: {count} 次")
    else:
        print("\n错误: 数据中没有 'winner_algo' 列")
        
    # 分析WMAPE
    if 'wmape' in df.columns:
        print(f"\nWMAPE统计:")
        print(f"  平均值: {df['wmape'].mean():.4f}")
        print(f"  最小值: {df['wmape'].min():.4f}")
        print(f"  最大值: {df['wmape'].max():.4f}")
    else:
        print("\n错误: 数据中没有 'wmape' 列")
        
except Exception as e:
    print(f"错误: {e}")
    traceback.print_exc()