import pandas as pd
import os

print("测试数据读取...")

# 读取CSV文件
csv_file = 'D:/华熠/output/spu_forecast_2026-03-12.csv'
print(f"文件路径: {csv_file}")
print(f"文件存在: {os.path.exists(csv_file)}")

if not os.path.exists(csv_file):
    print("文件不存在！")
    exit(1)

# 读取数据
try:
    df = pd.read_csv(csv_file)
    print(f"读取成功，数据条数: {len(df)}")
    print(f"列名: {list(df.columns)}")
    
    # 基本分析
    spu_count = df['spu'].nunique()
    print(f"SPU数量: {spu_count}")
    
    model_counts = df['winner_algo'].value_counts()
    print("模型使用情况:")
    print(model_counts)
    
    wmape_mean = df['validation_wmape'].mean()
    print(f"平均WMAPE: {wmape_mean:.6f}")
    
    print("测试成功！")
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
