#!/usr/bin/env python3
"""
预测分析工作脚本
独立于API服务运行，避免multiprocessing冲突
"""
import os
import sys
import json

# 立即输出启动信息
print("WORKER_START: 工作脚本启动", flush=True)

try:
    import pandas as pd
    print("WORKER_IMPORT: pandas导入成功", flush=True)
except Exception as e:
    print(f"WORKER_ERROR: pandas导入失败: {str(e)}", flush=True)
    sys.exit(1)

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
print(f"WORKER_PATH: 项目路径已添加: {sys.path[0]}", flush=True)

try:
    print("WORKER_IMPORT: 开始导入执行桥接模块...", flush=True)
    from src.forecasting.execution_bridge import get_data_from_db, process_single_spu, save_to_database
    print("WORKER_IMPORT: 执行桥接模块导入成功", flush=True)
except Exception as e:
    print(f"WORKER_ERROR: 执行桥接模块导入失败: {str(e)}", flush=True)
    import traceback
    print(traceback.format_exc(), flush=True)
    sys.exit(1)

def run_analysis(db_url, params=None):
    """执行预测分析并返回结果"""
    if params is None:
        params = {'mode': 'smart'}
    
    mode = params.get('mode', 'smart')
    
    try:
        print(f"开始执行分析，运行模式: {mode}")
        print(f"数据库URL: {db_url}")
        print(f"参数: {params}", flush=True)
        # 获取数据
        print("正在获取数据...")
        df_all = get_data_from_db(db_url)
        print(f"获取到 {len(df_all)} 条数据")
        df_all['sales'] = pd.to_numeric(df_all['sales'], errors='coerce').fillna(0)
        df_all['date']  = pd.to_datetime(df_all['date'], format='mixed')
        df_all['spu']   = df_all['spu'].astype(str)
        df_all['sku']   = df_all['sku'].astype(str)
        print(f"数据处理完成，唯一SPU数量: {len(df_all['spu'].unique())}")
        
        spus = df_all['spu'].unique()
        exog_cols = [c for c in df_all.columns if c in ['ad_cost', 'price']]
        
        all_res, failed_spus = [], []
        
        total_spus = len(spus)
        
        for i, spu in enumerate(spus, 1):
            # 输出进度信息 - 基于实际完成的SPU数量
            progress = (i / total_spus) * 100
            print(f"PROGRESS:{int(progress)}")
            print(f"CURRENT_SPU:{spu}")
            print(f"PROCESSED_COUNT:{i}")
            print(f"TOTAL_COUNT:{total_spus}")
            sys.stdout.flush()
            
            # 为每个SPU准备数据
            df_spu = df_all[df_all['spu'] == spu].copy()
            res, msg, viz, profile = process_single_spu(
                spu, df_spu, mode=mode,
                exog_cols=exog_cols, collect_viz=True, verbose=False,
                sku_accuracy_threshold=0.01
            )
            
            if res is not None and viz is not None:
                all_res.append(res)
            else:
                failed_spus.append({'spu': spu, 'reason': msg})
        
        # 整理结果
        if all_res:
            final = pd.concat(all_res, ignore_index=True)
            
            # 保存到数据库
            save_to_database(final, db_url)
            print("DATABASE_WRITE:SUCCESS")
            
            # 计算平均误差率
            if 'validation_wmape' in final.columns:
                average_wmape = final['validation_wmape'].mean()
            else:
                average_wmape = None
            
            # 找出表现最好和最差的SPU
            if 'validation_wmape' in final.columns and 'spu' in final.columns:
                # 按误差率排序
                sorted_spus = final.groupby('spu')['validation_wmape'].mean().sort_values()
                # 获取表现最好的3个SPU
                top_performing_spus = sorted_spus.head(3).index.tolist()
                # 获取表现最差的3个SPU
                bottom_performing_spus = sorted_spus.tail(3).index.tolist()
            else:
                top_performing_spus = []
                bottom_performing_spus = []
            
            result = {
                "success": True,
                "total_spus": total_spus,
                "successful_spus": len(all_res),
                "failed_spus": len(failed_spus),
                "failed_details": failed_spus,
                "average_wmape": average_wmape,
                "top_performing_spus": top_performing_spus,
                "bottom_performing_spus": bottom_performing_spus
            }
        else:
            result = {
                "success": False,
                "message": "所有SPU预测失败",
                "failed_spus": failed_spus,
                "average_wmape": None,
                "top_performing_spus": [],
                "bottom_performing_spus": []
            }
        
        return result
        
    except Exception as e:
        import traceback
        error_message = f"分析失败: {str(e)}"
        print(f"ERROR:{error_message}")
        print(traceback.format_exc())
        return {
            "success": False,
            "message": error_message
        }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analysis_worker.py <db_url> [params_json]")
        sys.exit(1)
    
    db_url = sys.argv[1]
    
    # 解析params参数
    params = None
    if len(sys.argv) > 2:
        try:
            params = json.loads(sys.argv[2])
            print(f"WORKER_PARAMS: 接收到的参数: {params}", flush=True)
        except Exception as e:
            print(f"WORKER_ERROR: 解析参数失败: {str(e)}", flush=True)
            # 如果解析失败，使用第二个参数作为mode
            params = {'mode': sys.argv[2]}
    
    if params is None:
        params = {'mode': 'smart'}
    
    result = run_analysis(db_url, params)
    print(f"RESULT:{json.dumps(result, ensure_ascii=False)}")
