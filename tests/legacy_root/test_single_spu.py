import pandas as pd
import numpy as np
import json
import traceback
from src.forecasting.main import process_single_spu, get_data_from_db

print("=== 测试单个SPU的SKU回测功能 ===")

# 获取数据
try:
    print("1. 获取数据...")
    df_all = get_data_from_db("postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    print(f"   数据加载完成，共 {len(df_all)} 行")
    print(f"   唯一SPU数量: {len(df_all['spu'].unique())}")
    
    # 选择一个SPU进行测试
    spus = df_all['spu'].unique()
    if len(spus) > 0:
        test_spu = spus[0]
        print(f"   选择测试SPU: {test_spu}")
        
        # 处理单个SPU
        print("2. 处理单个SPU...")
        res, msg, viz, profile = process_single_spu(test_spu, df_all, mode='smart', collect_viz=True, verbose=True)
        
        if res is not None:
            print(f"   处理成功: {msg}")
            
            # 查看结果
            print("3. 查看结果...")
            print(f"   预测周数: {len(res)}")
            
            # 查看第一个预测结果的SKU回测数据
            if not res.empty:
                first_row = res.iloc[0]
                print(f"   第一个预测日期: {first_row['forecast_target_date']}")
                
                # 解析SKU权重JSON
                sku_share_json = first_row['sku_share_json']
                try:
                    sku_data = json.loads(sku_share_json)
                    print(f"   SKU数量: {len(sku_data)}")
                    
                    # 打印第一个SKU的回测数据
                    if sku_data:
                        first_sku = list(sku_data.keys())[0]
                        sku_info = sku_data[first_sku]
                        print(f"   第一个SKU: {first_sku}")
                        print(f"   权重: {sku_info['weight']:.4f}")
                        
                        if 'backtest' in sku_info:
                            backtest = sku_info['backtest']
                            print(f"   真实值数量: {len(backtest['real_values'])}")
                            print(f"   预测值数量: {len(backtest['pred_values'])}")
                            print(f"   WMAPE: {backtest['wmape']:.4f}")
                            print(f"   真实值示例: {backtest['real_values'][:3]}...")
                            print(f"   预测值示例: {backtest['pred_values'][:3]}...")
                except json.JSONDecodeError as e:
                    print(f"   JSON解析错误: {e}")
        else:
            print(f"   处理失败: {msg}")
    else:
        print("   没有找到SPU数据")
        
except Exception as e:
    print(f"   错误: {e}")
    traceback.print_exc()

print("\n=== 测试完成 ===")