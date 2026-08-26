import sys
import os
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
    calculate_dynamic_shares, calculate_principal_dynamic_shares
)
from algorithm_engine import *

# 加载 .env 文件中的环境变量
from dotenv import load_dotenv
load_dotenv()





def process_single_spu(spu, df_spu, mode='smart', exog_cols=None, collect_viz=False, verbose=True, sku_accuracy_threshold=0.01):
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
            future_exog = build_future_exog_frame(exog_series, future_dates_exog)

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

        # ✅ SKU 份额预测：json_list 写库，share_df 绘图
        share_json_list, share_df = calculate_dynamic_shares(df_spu_idx, spu, series_clean, future_dates)
        # ✅ 负责人权重预测：仅作为 JSON 字段写入，不改变入库颗粒度
        principal_share_json_list, _principal_share_df = calculate_principal_dynamic_shares(
            df_spu_idx, series_clean, future_dates
        )
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
            'principal_share_json': principal_share_json_list,
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
    # ✅ 核心修复：用完立即销毁 engine，不让连接在训练期间空挂
    print("正在从数据库拉取训练数据，这可能需要一些时间...")
    t0 = time.time()
    # 支持通过环境变量 SPU_LIST 指定 SPU 范围；不设置则全量
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
        coalesce(a.principal_names, 'UNKNOWN') as principal_names,
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
        group by 1,2,3,4
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           max(principal_names) as principal_names,
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
        # 返回空DataFrame，避免程序崩溃
        return pd.DataFrame()
    finally:
        engine.dispose()
        print("数据库连接已关闭")


def save_to_database(df_spu_level, db_url):
    print("\n正在将 SPU 级预测结果及 SKU 占比 JSON 写入数据库...")

    df_db = df_spu_level.copy()

    # ✅ 所有日期列强制转成 Python 原生 date，兼容 PostgreSQL DATE 类型
    for col in ['run_date', 'forecast_target_date', 'data_end_date']:
        if col in df_db.columns:
            df_db[col] = pd.to_datetime(df_db[col]).dt.date

    # 移除create_time字段，因为数据库表中可能没有这个字段
    # df_db['create_time'] = datetime.datetime.now()
    df_db['sku_share_json']    = df_db['sku_share_json'].astype(str)
    df_db['sku_accuracy_json'] = df_db['sku_accuracy_json'].astype(str) # ✅ 新增字段类型转换
    df_db['best_params']       = df_db['best_params'].astype(str)
    df_db['training_weeks']    = df_db['training_weeks'].astype(int)
    df_db['has_exog_features'] = df_db['has_exog_features'].astype(bool)

    print(f"   准备写入 {len(df_db)} 行")
    print(f"   列名及类型:\n{df_db.dtypes.to_string()}")
    print(f"   数据预览:\n{df_db[['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value']].head(3).to_string()}")

    # 检查列名是否与数据库表结构匹配
    expected_columns = ['spu', 'run_date', 'forecast_target_date', 'spu_forecast_value', 
                       'sku_share_json', 'seasonal_factors_json', 'sku_accuracy_json', 
                       'winner_algo', 'validation_wmape', 'best_params', 'has_exog_features', 
                       'exog_columns', 'training_weeks', 'data_end_date']
    
    actual_columns = list(df_db.columns)
    missing_columns = [col for col in expected_columns if col not in actual_columns]
    extra_columns = [col for col in actual_columns if col not in expected_columns]
    
    print(f"   预期列: {expected_columns}")
    print(f"   实际列: {actual_columns}")
    if missing_columns:
        print(f"   缺少列: {missing_columns}")
    if extra_columns:
        print(f"   多余列: {extra_columns}")

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
            # 检查表是否存在
            check_table_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'finedatalink' 
                AND table_name = 'sales_forecast_history'
            )
            """)
            table_exists = conn.execute(check_table_query).scalar()
            print(f"   表是否存在: {table_exists}")
            
            if not table_exists:
                print("   表不存在，创建表结构...")
                # 创建表结构
                create_table_query = text("""
                CREATE TABLE IF NOT EXISTS finedatalink.sales_forecast_history (
                    id SERIAL PRIMARY KEY,
                    spu VARCHAR(50) NOT NULL,
                    run_date DATE NOT NULL,
                    forecast_target_date DATE NOT NULL,
                    spu_forecast_value NUMERIC(18,4) NOT NULL,
                    sku_share_json TEXT,
                    seasonal_factors_json TEXT,
                    sku_accuracy_json TEXT,
                    winner_algo VARCHAR(100),
                    validation_wmape NUMERIC(10,4),
                    best_params TEXT,
                    has_exog_features BOOLEAN,
                    exog_columns VARCHAR(255),
                    training_weeks INTEGER,
                    data_end_date DATE
                )
                """)
                conn.execute(create_table_query)
                print("   表创建成功")
            
            # 清理旧记录
            run_dates = df_db['run_date'].unique()
            for rd in run_dates:
                del_query = text("DELETE FROM finedatalink.sales_forecast_history WHERE run_date = :rd")
                # 直接使用date对象，而不是转换为字符串
                result = conn.execute(del_query, {"rd": rd})
                print(f"   已清理 run_date={rd} 旧记录 {result.rowcount} 条，准备幂等写入...")

            # 写入数据
            print("   开始写入数据...")
            # 只选择预期的列
            df_db = df_db[expected_columns]
            print(f"   写入列: {list(df_db.columns)}")
            
            # 分批次写入
            batch_size = 100
            total_rows = len(df_db)
            for i in range(0, total_rows, batch_size):
                batch = df_db.iloc[i:i+batch_size]
                print(f"   写入批次 {i//batch_size + 1}/{(total_rows + batch_size - 1)//batch_size}，行数: {len(batch)}")
                batch.to_sql(
                    'sales_forecast_history',
                    con=conn,
                    schema='finedatalink',
                    if_exists='append',
                    index=False,
                    method='multi'
                )
            
        print(f"数据库写入成功! 目标表: finedatalink.sales_forecast_history，共写入 {len(df_db)} 条 SPU 级记录")

    except Exception as e:
        import traceback
        print("数据库写入失败，详细错误如下:")
        traceback.print_exc()
        backup_file = os.path.join('D:/华熠/output', f'backup_{datetime.date.today()}.csv')
        try:
            os.makedirs('D:/华熠/output', exist_ok=True)
            df_spu_level.to_csv(backup_file, index=False)
            print(f"   已保存本地备份: {backup_file}")
        except Exception as backup_err:
            print(f"   备份也失败了: {backup_err}")
    finally:
        engine.dispose()


def main():
    SAVE_PLOT_DIR  = 'D:/华熠/plots'
    OUTPUT_DIR     = 'D:/华熠/output'
    REPORT_DIR     = 'D:/华熠/reports'

    RUN_MODE        = 'smart'   # 可选: 'fast' | 'smart' | 'full'
    SHOW_PLOTS      = True
    SAVE_PLOTS      = True
    ENABLE_DB_WRITE = True
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # --- Configurable Parameters ---
    SKU_ACCURACY_THRESHOLD = float(os.getenv("SKU_ACCURACY_THRESHOLD", 0.01)) # Filter SKUs with sales < 1% of SPU total
    
    print("=" * 70)
    print("SPU 销售预测引擎 v8.5 (SPU+SKU 联合可视化版)")
    print(f"   运行模式: {RUN_MODE.upper()}")
    print(f"   SKU 评估阈值: {SKU_ACCURACY_THRESHOLD:.1%}")
    print("=" * 70)

    for d in [SAVE_PLOT_DIR, OUTPUT_DIR, REPORT_DIR]:
        os.makedirs(d, exist_ok=True)

    global_best_wmape, global_best_viz = float('inf'), None

    # 初始化
    setup_logging()
    logging.info("SPU 销售预测引擎启动")
    
    # 1. 获取数据
    try:
        df_all = get_data_from_db(DB_URL)
        df_all['sales'] = pd.to_numeric(df_all['sales'], errors='coerce').fillna(0)
        df_all['date']  = pd.to_datetime(df_all['date'], format='mixed')
        df_all['spu']   = df_all['spu'].astype(str)
        df_all['sku']   = df_all['sku'].astype(str)

        spus = df_all['spu'].unique()
        print(f"   发现 {len(spus)} 个目标 SPU")

        exog_cols = [c for c in df_all.columns if c in ['ad_cost', 'price']]
        if exog_cols:
            print(f"   使用外生变量: {exog_cols}")

        all_res, failed_spus, all_reports = [], [], []

        # Initialize profiler for report generation
        profiler = SPUProfiler(verbose=False)

        # Parallel Execution Setup
        cpu_count = os.cpu_count() or 1
        max_workers = min(cpu_count, 6) # Increase slightly as some tasks might be IO bound (though mostly CPU)
        print(f"启动并行处理 (Workers={max_workers})...")
        
        # Pre-group data to avoid repeated filtering in loop
        print("   正在为并行处理准备数据分组...")
        spu_data_map = {s: df_all[df_all['spu'] == s].copy() for s in spus}

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_spu = {
                executor.submit(
                    process_single_spu, 
                    spu, 
                    spu_data_map[spu], 
                    mode=RUN_MODE, 
                    exog_cols=exog_cols, 
                    collect_viz=True, 
                    verbose=False,
                    sku_accuracy_threshold=SKU_ACCURACY_THRESHOLD
                ): spu for spu in spus
            }
            
            completed_count = 0
            total_spus = len(spus)
            
            print(f"   开始处理 {total_spus} 个 SPU...")
            
            for future in concurrent.futures.as_completed(future_to_spu):
                spu = future_to_spu[future]
                completed_count += 1
                try:
                    res, msg, viz, profile = future.result()
                    print(f"[{completed_count}/{total_spus}] {spu}: {msg}")
                    if res is not None:
                        all_res.append(res)
                        if viz is not None and profile is not None and profile.winner_wmape < global_best_wmape:
                            global_best_wmape, global_best_viz = profile.winner_wmape, viz
                            print(f"   当前暂列第一! WMAPE: {global_best_wmape:.2%}")
                        if profile is not None:
                            all_reports.append(profiler.generate_report_dict(profile))
                    else:
                        failed_spus.append({'spu': spu, 'reason': msg})
                except Exception as e:
                    print(f"[{completed_count}/{total_spus}] {spu}: 异常: {e}")
                    failed_spus.append({'spu': spu, 'reason': str(e)})

        print("\n" + "=" * 70 + "\n批量处理完成!\n" + "=" * 70)

        if all_res:
            final = pd.concat(all_res, ignore_index=True)
            print(f"\n成功: {len(all_res)}/{len(spus)} 个 SPU")

            print("\n胜出模型统计:")
            print(final.groupby('winner_algo')['spu'].nunique().sort_values(ascending=False).to_string())

            # 确保输出目录存在
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            os.makedirs(REPORT_DIR, exist_ok=True)
            
            output_file = os.path.join(OUTPUT_DIR, f'spu_forecast_{datetime.date.today()}.csv')
            final.to_csv(output_file, index=False)
            print(f"\n   CSV 已保存至: {output_file}")

            report_file = os.path.join(REPORT_DIR, f'spu_profiles_{datetime.date.today()}.json')
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(all_reports, f, ensure_ascii=False, indent=2, default=str)
            print(f"   模型报告已保存至: {report_file}")

            if ENABLE_DB_WRITE:
                save_to_database(final, DB_URL)

        # ── 全程只在这里弹出一张图：全场误差最小的 SPU ──
        if global_best_viz:
            best_spu = global_best_viz['profile'].spu
            print(f"\n正在生成全场最佳 SPU 预测图表: {best_spu} (WMAPE: {global_best_wmape:.2%})")
            best_save_path = os.path.join(SAVE_PLOT_DIR, f"BEST_{best_spu}.png") if SAVE_PLOTS else None
            # ✅ 传入 sku_future_df
            plot_best_spu_style(
                global_best_viz['profile'],
                global_best_viz['train'],
                global_best_viz['test'],
                global_best_viz['results'],
                global_best_viz['future'],
                global_best_viz['dates'],
                sku_future_df=global_best_viz.get('sku_future_df'),
                save_path=best_save_path,
                show_plot=SHOW_PLOTS
            )

        if failed_spus:
            print(f"\n失败 ({len(failed_spus)}):")
            for f in failed_spus[:5]:
                print(f"   - {f['spu']}: {f['reason']}")

    except Exception as e:
        import traceback
        print(f"\n严重错误: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
