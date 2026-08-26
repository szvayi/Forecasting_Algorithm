#!/usr/bin/env python3
"""
SPU销售预测引擎 - 测试版本
支持前端调用，提供实时日志输出和进度汇报
"""
import sys
import os

# 设置stdout编码为UTF-8，解决Windows下emoji输出问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import datetime
import time
import pandas as pd
import numpy as np
import json
import multiprocessing
import concurrent.futures
from sqlalchemy import create_engine, text
from config_and_utils import (
    SPUProfiler, SPUProfile, setup_logging, get_current_week_end, clean_series,
    calculate_wmape, detect_seasonality_strength, extract_seasonal_pattern,
    clean_params_for_db, plot_best_spu_style, extract_seasonal_factors_52week,
    calculate_dynamic_shares
)
from algorithm_engine import *

# 加载 .env 文件中的环境变量
from dotenv import load_dotenv
load_dotenv()

# 全局变量用于存储进度信息（供前端读取）
_analysis_state = {
    "status": "idle",  # idle, running, completed, failed
    "progress": 0,  # 0-100
    "current_spu": "",
    "processed_count": 0,
    "total_count": 0,
    "logs": [],  # 存储日志信息
    "completed_spus": [],  # 存储已完成的SPU结果
    "error": None,
    "result": None
}

def log_message(message, message_type="info"):
    """记录日志并输出到stdout（供前端捕获）"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "type": message_type,  # info, success, warning, error
        "message": message
    }
    _analysis_state["logs"].append(log_entry)
    # 限制日志数量，防止内存溢出
    if len(_analysis_state["logs"]) > 1000:
        _analysis_state["logs"] = _analysis_state["logs"][-500:]
    
    # 输出到stdout，保持与main.py相同的格式
    print(message, flush=True)

def update_progress(processed, total, current_spu=""):
    """更新进度信息"""
    _analysis_state["processed_count"] = processed
    _analysis_state["total_count"] = total
    _analysis_state["current_spu"] = current_spu
    _analysis_state["progress"] = int((processed / total * 100)) if total > 0 else 0
    
    print(f"PROGRESS:{_analysis_state['progress']}", flush=True)
    print(f"CURRENT_SPU:{current_spu}", flush=True)
    print(f"PROCESSED_COUNT:{processed}", flush=True)
    print(f"TOTAL_COUNT:{total}", flush=True)

def add_completed_spu(spu_name, winner_algo, wmape, status="success"):
    """添加已完成的SPU信息"""
    completed_info = {
        "spu": spu_name,
        "winner_algo": winner_algo,
        "wmape": round(wmape, 4) if wmape else None,
        "status": status,
        "completed_at": datetime.datetime.now().isoformat()
    }
    _analysis_state["completed_spus"].append(completed_info)
    print(f"COMPLETED_SPU:{json.dumps(completed_info, ensure_ascii=False)}", flush=True)

def get_analysis_state():
    """获取当前分析状态（供前端API调用）"""
    return _analysis_state.copy()

def reset_analysis_state():
    """重置分析状态"""
    global _analysis_state
    _analysis_state = {
        "status": "idle",
        "progress": 0,
        "current_spu": "",
        "processed_count": 0,
        "total_count": 0,
        "logs": [],
        "completed_spus": [],
        "error": None,
        "result": None
    }




def process_single_spu(spu, df_spu, mode='smart', exog_cols=None, collect_viz=False, verbose=True, sku_accuracy_threshold=0.01):
    """处理单个SPU的预测（与原版相同）"""
    t0 = time.time()
    try:
        # Initialize profiler
        profiler = SPUProfiler(verbose=verbose)
        
        # df_spu is now passed directly, ensuring we work on a slice/copy for this SPU
        df_spu_idx = df_spu.set_index('date').sort_index()

        series = df_spu_idx['sales'].resample('W').sum()
        current_week_end = get_current_week_end()
        series = series[series.index < current_week_end]
        original_series = series.copy()

        has_exog, exog_series, used_exog = False, None, []
        if exog_cols:
            available = [c for c in exog_cols if c in df_spu_idx.columns]
            if available:
                exog_df = pd.DataFrame(index=series.index)
                if 'ad_cost' in available:
                    exog_df['ad_cost'] = df_spu_idx['ad_cost'].resample('W').sum().fillna(0)
                if 'price' in available:
                    df_spu_idx['revenue'] = df_spu_idx['sales'] * df_spu_idx['price']
                    series_price = df_spu_idx['revenue'].resample('W').sum() / series.replace(0, np.nan)
                    exog_df['price'] = series_price.ffill().bfill().fillna(0)

                exog_series = exog_df[exog_df.index < current_week_end]
                has_exog, used_exog = True, available

        if len(series) > 156:
            series = series.iloc[-156:]
            original_series = original_series.iloc[-156:]
            if has_exog: exog_series = exog_series.iloc[-156:]

        series_clean = clean_series(series)
        if len(series_clean) < 12:
            return None, "数据不足 (<12周)", None, None

        profile = profiler.analyze(spu, series_clean, original_series, exog_series)
        if verbose: profiler.print_profile(profile)

        test_len = min(10, max(4, len(series_clean) // 3))
        train, test = series_clean.iloc[:-test_len], series_clean.iloc[-test_len:]
        train_exog = exog_series.iloc[:-test_len] if has_exog else None
        test_exog  = exog_series.iloc[-test_len:] if has_exog else None

        if verbose: print(f"\n模型竞赛中 (mode={mode})...")
        all_results, base_results = run_all_models(train, test, mode, train_exog, test_exog, verbose=False)
        if not all_results:
            fallback_pred_test = np.full(len(test), float(test.mean()) if test.mean() > 0 else float(series_clean.mean()))
            fallback_wmape = calculate_wmape(test, pd.Series(fallback_pred_test, index=test.index))
            winner = {'name': 'NaiveMean', 'forecast': fallback_pred_test.tolist(), 'wmape': float(fallback_wmape), 'params': {}}
            all_results = [winner]
        else:
            winner = min(all_results, key=lambda x: x['wmape'])

        future_exog = None
        if has_exog and exog_series is not None:
            future_dates_exog = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]
            future_exog_data = {}
            for c in exog_series.columns:
                future_exog_data[c] = [
                    exog_series[c].iloc[-4:].mean() if len(exog_series) >= 4 else exog_series[c].mean()
                ] * 16
            future_exog = pd.DataFrame(future_exog_data, index=future_dates_exog)

        final_preds = predict_future(series_clean, winner, 16, exog_series, future_exog, base_results)

        hist_cv = series_clean.std() / series_clean.mean() if series_clean.mean() > 0 else 0
        pred_cv = np.std(final_preds) / np.mean(final_preds) if np.mean(final_preds) > 0 else 0
        if verbose: print(f"   波动性检查: 历史CV={hist_cv:.3f}, 预测CV={pred_cv:.3f}, 比值={pred_cv / hist_cv:.2f}")
        if pred_cv < hist_cv * 0.3:
            if verbose: print(f"   警告: 预测波动性过低! 引擎已启动修正算法...")

        fallback_value = float(series_clean.iloc[-8:].mean())
        final_preds = safe_predictions(final_preds, fallback_value, winner['name'])

        total_time = time.time() - t0
        future_dates = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]
        profile = profiler.update_with_results(profile, train, test, all_results, winner, final_preds, total_time)

        if verbose:
            profiler.print_model_competition(profile)
            profiler.print_forecast_summary(profile, future_dates, final_preds)

        # ✅ 接收两个返回值：json_list 写库，share_df 绘图
        share_json_list, share_df = calculate_dynamic_shares(df_spu_idx, spu, series_clean, future_dates)
        # ✅ 提取 52 周季节因子
        seasonal_factors_json = extract_seasonal_factors_52week(series_clean, period=52)

        # --- 新增: SKU 预测准确性评估 (Backtesting on Validation Set) ---
        sku_accuracy_json = None
        try:
            # 1. 准备验证集数据 (Test period)
            val_dates = test.index
            train_end_date = val_dates[0] - pd.Timedelta(days=1)
            
            # 2. 仅使用训练集数据来计算份额逻辑
            df_train_idx = df_spu_idx[df_spu_idx.index <= train_end_date]
            train_spu_sales = series_clean[series_clean.index <= train_end_date]
            
            # 3. 预测验证集的份额
            # 注意: calculate_dynamic_shares 内部会重新聚合 df_train_idx，确保其逻辑与 train_spu_sales 一致
            _, val_share_df = calculate_dynamic_shares(df_train_idx, spu, train_spu_sales, val_dates)
            
            # 4. 获取胜出模型在验证集的 SPU 预测值
            # winner['forecast'] 是对 test (即 val_dates) 的预测
            winner_val_preds = pd.Series(winner['forecast'], index=val_dates)
            
            # 5. 计算 SKU 验证集预测值: SPU预测 * 预测份额
            sku_val_preds = val_share_df.multiply(winner_val_preds, axis=0)
            
            # 6. 获取 SKU 验证集真实值
            sku_val_actual = df_spu_idx[df_spu_idx.index.isin(val_dates)].groupby([pd.Grouper(freq='W'), 'sku'])['sales'].sum().unstack(fill_value=0)
            sku_val_actual = sku_val_actual.reindex(index=val_dates, columns=sku_val_preds.columns, fill_value=0)
            
            # 7. 计算每个 SKU 的 WMAPE
            sku_metrics = {}
            total_sku_sales = sku_val_actual.sum().sum()
            
            for sku in sku_val_preds.columns:
                actual = sku_val_actual[sku]
                pred = sku_val_preds[sku]
                sku_total = actual.sum()
                
                # 仅评估销量占比超过阈值的 SKU，避免长尾噪音
                if total_sku_sales > 0 and sku_total / total_sku_sales < sku_accuracy_threshold:
                    continue
                    
                wmape = calculate_wmape(actual, pred)
                sku_metrics[sku] = {
                    'wmape': round(wmape, 4),
                    'total_sales': float(sku_total),
                    'weight_in_spu': round(sku_total / total_sku_sales, 4) if total_sku_sales > 0 else 0
                }
            
            # 8. 转换为 JSON
            sku_accuracy_json = json.dumps(sku_metrics, ensure_ascii=False)
            
        except Exception as e:
            if verbose: print(f"   SKU 评估失败: {e}")
            sku_accuracy_json = json.dumps({"error": str(e)}, ensure_ascii=False)
        # -----------------------------------------------------------


        # ✅ SKU 实际预测销量 = 每周 SPU 预测值 × 该周各 SKU 占比权重
        sku_future_df = share_df.multiply(final_preds, axis=0)

        safe_best_params = clean_params_for_db(winner.get('params'))

        result_df = pd.DataFrame({
            'spu':                  spu,
            'run_date':             datetime.date.today(),
            # ✅ DatetimeIndex → Python date，彻底兼容 PostgreSQL DATE 类型
            'forecast_target_date': [d.date() for d in future_dates],
            'spu_forecast_value':   np.round(final_preds, 4),
            'sku_share_json':       share_json_list,
            'seasonal_factors_json': seasonal_factors_json,  # ✅ 新增字段
            'sku_accuracy_json':    sku_accuracy_json,       # ✅ 新增: SKU 准确性评估
            'winner_algo':          winner['name'],
            'validation_wmape':     round(winner['wmape'], 4),
            'best_params':          safe_best_params,
            'has_exog_features':    has_exog,
            'exog_columns':         ','.join(used_exog) if used_exog else None,
            'training_weeks':       int(len(series_clean)),
            'data_end_date':        series_clean.index[-1].date()
        })

        viz_data = {
            'profile':       profile,
            'train':         train,
            'test':          test,
            'results':       all_results,
            'future':        final_preds,
            'dates':         future_dates,
            'winner':        winner,
            'sku_future_df': sku_future_df,   # ✅ 新增：SKU 实际预测销量 DataFrame
        } if collect_viz else None

        return result_df, f"{winner['name']} (WMAPE: {winner['wmape']:.2%}) [{total_time:.1f}s]", viz_data, profile

    except Exception as e:
        import traceback; traceback.print_exc()
        return None, f"错误: {str(e)}", None, None


def get_data_from_db(db_url):
    """从数据库获取数据（与原版相同）"""
    print("正在从数据库拉取训练数据，这可能需要一些时间...")
    t0 = time.time()
    spu_list_env = os.getenv("SPU_LIST", "").strip()
    spu_filter_sql = ""
    if spu_list_env:
        tokens = [s.strip() for s in spu_list_env.split(",") if s.strip()]
        if tokens:
            in_list = ",".join([f"'{t}'" for t in tokens])
            spu_filter_sql = f" and SPU in ({in_list})"

    query = f"""
    with base as (
        select
        a."date" as report_date,
        local_sku,
        case 
        when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
        when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
        when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
        else '-' end as SPU,
        sum(afn_amount+mfn_amount+promotion_discount+refund_amount+cost_of_points_granted+inventory_credit+shared_fba_liquidation_proceeds+shared_fba_liquidation_proceeds_adjustments
        +shared_amazon_shipping_reimbursement+shared_safe_t_reimbursement+shared_netco_transaction+shared_reimbursements+shared_clawbacks+shared_commingling_vat_income+gift_wrap_credits
        +a_to_z_guarantee_claims+shared_others+shipping_cost) as 销售额,
        sum(a.volume) as 销量,
        avg(avg_net_amount) as 平均售价,
        sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        group by 1,2,3
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
    from base 
    where 1=1{spu_filter_sql}
    group by report_date, SPU, local_sku
    order by report_date
    """
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        print("尝试连接数据库...")
        with engine.connect() as conn:
            print("数据库连接成功！")
            print("开始执行SQL查询...")
            df = pd.read_sql(text(query), con=conn)
            print(f"SQL查询执行成功，获取到 {len(df)} 行数据")
        df.columns = [col.lower() for col in df.columns]
        print(f"数据获取完成！共加载 {len(df)} 行记录，耗时: {time.time() - t0:.1f} 秒")
        return df
    except Exception as e:
        import traceback
        print(f"数据获取失败: {e}")
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        engine.dispose()
        print("数据库连接已关闭")


def save_to_database(df_spu_level, db_url):
    """保存结果到数据库（与原版相同）"""
    print("\n正在将 SPU 级预测结果及 SKU 占比 JSON 写入数据库...")

    df_db = df_spu_level.copy()

    for col in ['run_date', 'forecast_target_date', 'data_end_date']:
        if col in df_db.columns:
            df_db[col] = pd.to_datetime(df_db[col]).dt.date

    df_db['sku_share_json']    = df_db['sku_share_json'].astype(str)
    df_db['sku_accuracy_json'] = df_db['sku_accuracy_json'].astype(str)
    df_db['best_params']       = df_db['best_params'].astype(str)
    df_db['training_weeks']    = df_db['training_weeks'].astype(int)
    df_db['has_exog_features'] = df_db['has_exog_features'].astype(bool)

    print(f"   准备写入 {len(df_db)} 行")

    expected_columns = ['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value', 
                       'sku_share_json', 'seasonal_factors_json', 'sku_accuracy_json', 
                       'winner_algo', 'validation_wmape', 'best_params', 'has_exog_features', 
                       'exog_columns', 'training_weeks', 'data_end_date']
    
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
        pool_size=1,
        max_overflow=0,
        pool_recycle=300
    )
    try:
        with engine.begin() as conn:
            run_dates = df_db['run_date'].unique()
            for rd in run_dates:
                del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd")
                result = conn.execute(del_query, {"rd": rd})
                print(f"   已清理 run_date={rd} 旧记录 {result.rowcount} 条")

            df_db = df_db[expected_columns]
            
            batch_size = 100
            total_rows = len(df_db)
            for i in range(0, total_rows, batch_size):
                batch = df_db.iloc[i:i+batch_size]
                batch.to_sql(
                    'sales_forecast_history',
                    con=conn,
                    schema='finedatalink',
                    if_exists='append',
                    index=False,
                    method='multi'
                )
            
        print(f"数据库写入成功! 共写入 {len(df_db)} 条 SPU 级记录")

    except Exception as e:
        import traceback
        print("数据库写入失败:")
        traceback.print_exc()
    finally:
        engine.dispose()


def run_analysis_with_progress(mode='smart', db_url=None):
    """
    执行分析并实时汇报进度（供前端调用）
    
    Args:
        mode: 运行模式 - 'fast', 'smart', 'full'
        db_url: 数据库连接URL
    """
    global _analysis_state
    reset_analysis_state()
    _analysis_state["status"] = "running"
    
    if db_url is None:
        db_url = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    log_message(f"=" * 70, "info")
    log_message(f"SPU 销售预测引擎 v8.5 (前端测试版)", "info")
    log_message(f"   运行模式: {mode.upper()}", "info")
    log_message(f"=" * 70, "info")
    
    try:
        # 1. 获取数据
        log_message("正在从数据库获取数据...", "info")
        df_all = get_data_from_db(db_url)
        
        if df_all.empty:
            log_message("数据获取失败，请检查数据库连接", "error")
            _analysis_state["status"] = "failed"
            _analysis_state["error"] = "数据获取失败"
            return _analysis_state
        
        df_all['sales'] = pd.to_numeric(df_all['sales'], errors='coerce').fillna(0)
        df_all['date']  = pd.to_datetime(df_all['date'], format='mixed')
        df_all['spu']   = df_all['spu'].astype(str)
        df_all['sku']   = df_all['sku'].astype(str)

        spus = df_all['spu'].unique()
        total_spus = len(spus)
        log_message(f"发现 {total_spus} 个目标 SPU", "success")
        
        _analysis_state["total_count"] = total_spus

        exog_cols = [c for c in df_all.columns if c in ['ad_cost', 'price']]
        if exog_cols:
            log_message(f"使用外生变量: {exog_cols}", "info")

        all_res, failed_spus, all_reports = [], [], []

        # Initialize profiler for report generation
        profiler = SPUProfiler(verbose=False)

        # Parallel Execution Setup
        cpu_count = os.cpu_count() or 1
        max_workers = min(cpu_count, 6)
        log_message(f"启动并行处理 (Workers={max_workers})...", "info")
        
        # Pre-group data to avoid repeated filtering in loop
        log_message("正在为并行处理准备数据分组...", "info")
        spu_data_map = {s: df_all[df_all['spu'] == s].copy() for s in spus}

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_spu = {
                executor.submit(
                    process_single_spu, 
                    spu, 
                    spu_data_map[spu], 
                    mode=mode, 
                    exog_cols=exog_cols, 
                    collect_viz=True, 
                    verbose=False,
                    sku_accuracy_threshold=0.01
                ): spu for spu in spus
            }
            
            completed_count = 0
            
            log_message(f"开始处理 {total_spus} 个 SPU...", "info")
            
            for future in concurrent.futures.as_completed(future_to_spu):
                spu = future_to_spu[future]
                completed_count += 1
                try:
                    res, msg, viz, profile = future.result()
                    update_progress(completed_count, total_spus, spu)
                    
                    if res is not None:
                        all_res.append(res)
                        log_message(f"[{completed_count}/{total_spus}] {spu}: {msg}", "success")
                        if profile is not None:
                            add_completed_spu(spu, profile.winner_name or 'N/A', profile.winner_wmape, "success")
                            all_reports.append(profiler.generate_report_dict(profile))
                    else:
                        failed_spus.append({'spu': spu, 'reason': msg})
                        log_message(f"[{completed_count}/{total_spus}] {spu}: 处理失败 - {msg}", "error")
                        add_completed_spu(spu, "N/A", None, "failed")
                        
                except Exception as e:
                    log_message(f"[{completed_count}/{total_spus}] {spu}: 异常 - {e}", "error")
                    failed_spus.append({'spu': spu, 'reason': str(e)})
                    add_completed_spu(spu, "N/A", None, "failed")
        
        update_progress(total_spus, total_spus, "")
        log_message("=" * 70, "info")
        log_message("批量处理完成!", "success")
        log_message("=" * 70, "info")

        if all_res:
            final = pd.concat(all_res, ignore_index=True)
            log_message(f"成功: {len(all_res)}/{total_spus} 个 SPU", "success")

            # 统计胜出模型
            winner_stats = final.groupby('winner_algo')['spu'].nunique().sort_values(ascending=False)
            log_message("\n胜出模型统计:", "info")
            for algo, count in winner_stats.items():
                log_message(f"   {algo}: {count} 个 SPU", "info")

            # 保存到数据库
            save_to_database(final, db_url)
            log_message("数据已保存到数据库", "success")
            
            # 计算汇总结果
            average_wmape = final['validation_wmape'].mean() if 'validation_wmape' in final.columns else None
            sorted_spus = final.groupby('spu')['validation_wmape'].mean().sort_values()
            top_performing_spus = sorted_spus.head(3).index.tolist()
            bottom_performing_spus = sorted_spus.tail(3).index.tolist()
            
            _analysis_state["result"] = {
                "success": True,
                "total_spus": total_spus,
                "successful_spus": len(all_res),
                "failed_spus": len(failed_spus),
                "average_wmape": average_wmape,
                "top_performing_spus": top_performing_spus,
                "bottom_performing_spus": bottom_performing_spus,
                "winner_stats": winner_stats.to_dict()
            }
        else:
            _analysis_state["result"] = {
                "success": False,
                "message": "所有SPU预测失败",
                "failed_spus": failed_spus
            }
        
        if failed_spus:
            log_message(f"\n失败 ({len(failed_spus)}):", "warning")
            for f in failed_spus[:5]:
                log_message(f"   - {f['spu']}: {f['reason']}", "warning")
        
        _analysis_state["status"] = "completed"
        log_message("分析完成!", "success")
        
    except Exception as e:
        import traceback
        error_msg = f"严重错误: {str(e)}"
        log_message(error_msg, "error")
        log_message(traceback.format_exc(), "error")
        _analysis_state["status"] = "failed"
        _analysis_state["error"] = error_msg
    
    return _analysis_state


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description='SPU销售预测引擎')
    parser.add_argument('--mode', type=str, default='smart', choices=['fast', 'smart', 'full'],
                       help='运行模式: fast(快速), smart(智能), full(完整)')
    parser.add_argument('--db-url', type=str, default=None,
                       help='数据库连接URL')
    args = parser.parse_args()
    
    result = run_analysis_with_progress(mode=args.mode, db_url=args.db_url)
    print(f"\n最终结果: {json.dumps(result, ensure_ascii=False, default=str)}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
