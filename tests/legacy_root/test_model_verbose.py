import sys
sys.path.insert(0, '.')

print("开始测试模型训练...")

import pandas as pd
import numpy as np
from src.forecasting.predictors import run_prophet, run_xgboost, run_lightgbm, run_all_models
from src.forecasting.models import SPUProfiler

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

# 从数据库加载一个SPU的数据
print("从数据库加载SPU 2141的数据...")
profiler = SPUProfiler(DB_URL)
train, test, train_exog, test_exog = profiler.get_data('2141')

if train is None or len(train) == 0:
    print("❌ 无法加载训练数据")
else:
    print(f"✅ 加载训练数据成功: {len(train)} 行")
    print(f"训练数据时间范围: {train.index.min()} 至 {train.index.max()}")
    print(f"测试数据时间范围: {test.index.min()} 至 {test.index.max()}")
    print(f"外生变量: {list(train_exog.columns) if train_exog is not None else 'None'}")
    
    # 测试运行所有模型
    print("\n开始运行所有模型 (verbose=True)...")
    models, base_results = run_all_models(train, test, mode='smart', train_exog=train_exog, test_exog=test_exog, verbose=True)
    
    print(f"\n模型运行结果: {len(models)} 个模型成功")
    for m in models:
        print(f"  - {m['name']}: WMAPE = {m['wmape']:.2%}")

print("\n测试完成!")