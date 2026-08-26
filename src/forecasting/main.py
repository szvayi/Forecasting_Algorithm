import os
import sys

# 添加当前目录到Python路径，确保可以导入src模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import datetime
import time
import pandas as pd
import numpy as np
import json
from sqlalchemy import create_engine, text
from src.forecasting.runtime_facade import build_future_exog_frame
from src.forecasting.predictors import *
from src.database.repositories import *
from src.utils.helpers import *


def calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates):
    # 确保sku_sales与spu_sales_weekly的时间范围一致
    sku_sales = df_spu_idx.groupby([pd.Grouper(freq='W'), 'sku'])['sales'].sum().unstack(fill_value=0)
    # 只保留与spu_sales_weekly相同的时间范围
    sku_sales = sku_sales[sku_sales.index.isin(spu_sales_weekly.index)]
    sku_sales = sku_sales.reindex(spu_sales_weekly.index, fill_value=0)

    spu_total = sku_sales.sum(axis=1)
    hist_shares = sku_sales.div(spu_total.replace(0, np.nan), axis=0).ffill().fillna(0)

    future_shares = {}
    for sku in hist_shares.columns:
        series = hist_shares[sku]
        if len(series) >= 4:
            recent_level = series.ewm(span=8, adjust=False).mean().iloc[-1]
            try: slope, _ = np.polyfit(np.arange(4), series.iloc[-4:].values, 1)
            except: slope = 0

            future_vals, curr = [], recent_level
            for _ in range(len(future_dates)):
                curr += slope * 0.3
                curr = max(0.001, min(1.0, curr))
                future_vals.append(curr); slope *= 0.8
            future_shares[sku] = future_vals
        else:
            future_shares[sku] = [series.mean() if len(series) > 0 else 0] * len(future_dates)

    future_df = pd.DataFrame(future_shares, index=future_dates)
    future_df = future_df.div(future_df.sum(axis=1), axis=0).fillna(0)

    # 计算SKU级别的回测数据
    def calculate_sku_backtest(row):
        sku_data = {}
        for sku in row.index:
            # 获取最近的SKU真实数据（最近10周）
            sku_real = sku_sales[sku].iloc[-10:].values if len(sku_sales) >= 10 else sku_sales[sku].values
            # 计算基于历史权重的预测值
            if len(hist_shares) >= 10:
                sku_pred = (spu_sales_weekly.iloc[-10:].values * hist_shares[sku].iloc[-10:].values).flatten()
            else:
                sku_pred = (spu_sales_weekly.values * hist_shares[sku].values).flatten()
            # 计算误差
            if len(sku_real) > 0 and len(sku_pred) > 0:
                min_len = min(len(sku_real), len(sku_pred))
                sku_real = sku_real[:min_len]
                sku_pred = sku_pred[:min_len]
                # 计算WMAPE
                mask = sku_real != 0
                if np.any(mask):
                    wmape = np.sum(np.abs(sku_real[mask] - sku_pred[mask])) / np.sum(np.abs(sku_real[mask]))
                else:
                    wmape = 0
            else:
                wmape = 0
            # 构建SKU数据字典
            sku_data[sku] = {
                'weight': float(row[sku]),
                'backtest': {
                    'real_values': sku_real.tolist(),
                    'pred_values': sku_pred.tolist(),
                    'wmape': float(wmape)
                }
            }
        return json.dumps(sku_data, ensure_ascii=False)

    # ✅ 同时返回 JSON 列表（写库用，包含回测数据）和 share_df（绘图用，值为占比 0~1）
    json_list = future_df.apply(calculate_sku_backtest, axis=1).values
    return json_list, future_df


def process_single_spu(spu, df_all, mode='smart', exog_cols=None, collect_viz=False, verbose=True):
    t0 = time.time()
    try:
        df_spu = df_all[df_all['spu'] == spu].copy()
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
        if len(series_clean) < 30:
            return None, "数据不足 (<30周)", None, None

        # 确保exog_series与series_clean的长度匹配
        if has_exog and exog_series is not None:
            # 重新索引exog_series，使其与series_clean的索引一致
            exog_series = exog_series.reindex(series_clean.index).fillna(0)

        train, test = series_clean.iloc[:-10], series_clean.iloc[-10:]
        train_exog = exog_series.iloc[:-10] if has_exog else None
        test_exog  = exog_series.iloc[-10:] if has_exog else None

        print(f"\n模型竞赛中 (mode={mode})...")
        all_results, base_results = run_all_models(train, test, mode, train_exog, test_exog, verbose=True)

        if not all_results:
            return None, "所有模型失败", None, None

        winner = min(all_results, key=lambda x: x['wmape'])

        future_exog = None
        if has_exog and exog_series is not None:
            future_dates_exog = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]
            future_exog = build_future_exog_frame(exog_series, future_dates_exog)

        final_preds = predict_future(series_clean, winner, 16, exog_series, future_exog, base_results)

        hist_cv = series_clean.std() / series_clean.mean() if series_clean.mean() > 0 else 0
        pred_cv = np.std(final_preds) / np.mean(final_preds) if np.mean(final_preds) > 0 else 0
        print(f"   波动性检查: 历史CV={hist_cv:.3f}, 预测CV={pred_cv:.3f}, 比值={pred_cv / hist_cv:.2f}")
        if pred_cv < hist_cv * 0.3:
            print(f"   警告: 预测波动性过低! 引擎已启动修正算法...")

        fallback_value = float(series_clean.iloc[-8:].mean())
        final_preds = safe_predictions(final_preds, fallback_value, winner['name'])

        total_time = time.time() - t0
        future_dates = pd.date_range(series_clean.index[-1], periods=17, freq='W')[1:]

        if verbose:
            print(f"   模型竞赛结果: {winner['name']} (WMAPE: {winner['wmape']:.2%})")
            print(f"   预测完成: {len(future_dates)} 周")

        # ✅ 接收两个返回值：json_list 写库，share_df 绘图
        share_json_list, share_df = calculate_dynamic_shares(df_spu_idx, spu, series_clean, future_dates)
        # ✅ 提取 52 周季节因子
        seasonal_factors_json = extract_seasonal_factors_52week(series_clean, period=52)


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
            'winner_algo':          winner['name'],
            'validation_wmape':     round(winner['wmape'], 4),
            'best_params':          safe_best_params,
            'has_exog_features':    has_exog,
            'exog_columns':         ','.join(used_exog) if used_exog else None,
            'training_weeks':       int(len(series_clean)),
            'data_end_date':        series_clean.index[-1].date()
        })

        viz_data = {
            'train':         train,
            'test':          test,
            'results':       all_results,
            'future':        final_preds,
            'dates':         future_dates,
            'winner':        winner,
            'sku_future_df': sku_future_df,   # ✅ 新增：SKU 实际预测销量 DataFrame
        } if collect_viz else None

        return result_df, f"🏆 {winner['name']} (WMAPE: {winner['wmape']:.2%}) [{total_time:.1f}s]", viz_data, None

    except Exception as e:
        import traceback; traceback.print_exc()
        return None, f"错误: {str(e)}", None, None


def get_data_from_db(db_url):
    # ✅ 核心修复：用完立即销毁 engine，不让连接在训练期间空挂
    print("正在从数据库拉取训练数据，这可能需要一些时间...")
    t0 = time.time()
    # 使用简化的查询，只查询最近3个月的数据，加快查询速度
    query = """
    with base as (
        select
        a."date" as report_date,
        a.msku as local_sku,
        case 
        when substring(a.msku,1,5)='RHNWB' then substring(a.msku,6,4)
        when substring(a.msku,1,2)='VY' then substring(a.msku,5,4)
        when substring(a.msku,1,2)='WB' then substring(a.msku,3,4)
        else '-' end as SPU,
        sum(a.volume) as 销量,
        sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费,
        avg(avg_net_amount) as 平均售价
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        group by 1,2,3
    ),
    SPU_list as (
        SELECT '2141' AS SPU UNION ALL 
        SELECT '2062' UNION ALL 
        SELECT '2029' UNION ALL 
        SELECT '2046' UNION ALL 
        SELECT '2026' UNION ALL 
        SELECT '3022' UNION ALL 
        SELECT '1930' UNION ALL 
        SELECT '2214' UNION ALL 
        SELECT '2033' UNION ALL 
        SELECT '2038' UNION ALL 
        SELECT '2208' UNION ALL 
        SELECT '2012' UNION ALL 
        SELECT '3050' UNION ALL 
        SELECT '2176' UNION ALL 
        SELECT '3033' UNION ALL 
        SELECT '2192' UNION ALL 
        SELECT '2213' UNION ALL 
        SELECT '3063' UNION ALL 
        SELECT '2224' UNION ALL 
        SELECT '3058' UNION ALL 
        SELECT '2073' UNION ALL 
        SELECT '3013' UNION ALL 
        SELECT '2165' UNION ALL 
        SELECT '3084' UNION ALL 
        SELECT '1976' UNION ALL 
        SELECT '2197' UNION ALL 
        SELECT '1476' UNION ALL 
        SELECT '1533' UNION ALL 
        SELECT '887' UNION ALL 
        SELECT '1577' UNION ALL 
        SELECT '1750' UNION ALL 
        SELECT '1512' UNION ALL 
        SELECT '1657' UNION ALL 
        SELECT '1983' UNION ALL 
        SELECT '1318' 
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
    from base 
    where 1=1 and SPU in (select SPU from SPU_list)
    group by report_date, SPU, local_sku
    order by report_date
    """
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        print("执行SQL查询...")
        print(f"查询长度: {len(query)} 字符")
        print("预计数据量: 无限制")
        t1 = time.time()
        with engine.connect() as conn:
            df = pd.read_sql(text(query), con=conn)
        t2 = time.time()
        print(f"查询执行完成，耗时: {t2 - t1:.1f} 秒")
        print(f"处理数据...")
        df.columns = [col.lower() for col in df.columns]
        print(f"数据获取完成！共加载 {len(df)} 行记录，总耗时: {time.time() - t0:.1f} 秒")
        print(f"唯一SPU数量: {len(df['spu'].unique())}")
        print(f"SPU列表: {sorted(df['spu'].unique())[:10]}...")
        return df
    except Exception as e:
        print(f"查询失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        engine.dispose()
        print("数据库连接已关闭")


def main():
    SAVE_PLOT_DIR  = 'D:/华熠/plots'
    OUTPUT_DIR     = 'D:/华熠/output'
    REPORT_DIR     = 'D:/华熠/reports'

    RUN_MODE        = 'smart'   # 可选: 'fast' | 'smart' | 'full'
    SHOW_PLOTS      = False
    SAVE_PLOTS      = False
    ENABLE_DB_WRITE = True
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

    print("=" * 70)
    print("SPU 销售预测引擎 v8.4 (SPU+SKU 联合可视化版)")
    print(f"   运行模式: {RUN_MODE.upper()}")
    print("   时间: " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print(f"   数据库URL: {DB_URL}")
    print("=" * 70)

    for d in [SAVE_PLOT_DIR, OUTPUT_DIR, REPORT_DIR]:
        os.makedirs(d, exist_ok=True)

    global_best_wmape, global_best_viz = float('inf'), None

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

        all_res, failed_spus = [], []

        for i, spu in enumerate(spus, 1):
            print(f"\n{'=' * 70}\n[{i}/{len(spus)}] 处理 SPU: {spu}\n{'=' * 70}")
            res, msg, viz, profile = process_single_spu(
                spu, df_all, mode=RUN_MODE,
                exog_cols=exog_cols, collect_viz=True, verbose=True
            )
            print(f"\n   结果: {msg}")

            if res is not None and viz is not None:
                all_res.append(res)
                if viz['winner']['wmape'] < global_best_wmape:
                    global_best_wmape, global_best_viz = viz['winner']['wmape'], viz
                    print(f"   当前暂列第一! WMAPE: {global_best_wmape:.2%}")
            else:
                failed_spus.append({'spu': spu, 'reason': msg})

        print("\n" + "=" * 70 + "\n批量处理完成!\n" + "=" * 70)

        if all_res:
            final = pd.concat(all_res, ignore_index=True)
            print(f"\n成功: {len(all_res)}/{len(spus)} 个 SPU")

            print("\n胜出模型统计:")
            print(final.groupby('winner_algo')['spu'].nunique().sort_values(ascending=False).to_string())

            output_file = os.path.join(OUTPUT_DIR, f'spu_forecast_{datetime.date.today()}.csv')
            final.to_csv(output_file, index=False)
            print(f"\n   CSV 已保存至: {output_file}")

            if ENABLE_DB_WRITE:
                save_to_database(final, DB_URL)

        if failed_spus:
            print(f"\n失败 ({len(failed_spus)}):")
            for f in failed_spus[:5]:
                print(f"   - {f['spu']}: {f['reason']}")

    except Exception as e:
        import traceback
        print(f"\n严重错误: {e}")
        traceback.print_exc()


def test_forecast():
    """测试预测功能"""
    print("开始测试预测功能...")
    print("当前时间:", datetime.datetime.now())
    
    # 测试数据库连接
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    print("数据库URL:", DB_URL)
    
    try:
        # 测试数据库连接
        engine = create_engine(DB_URL, pool_pre_ping=True)
        print("✓ 数据库连接成功")
        
        # 测试获取数据
        print("测试获取数据...")
        df = get_data_from_db(DB_URL)
        print(f"✓ 获取数据成功: {len(df)} 条记录")
        print(f"✓ 发现 {len(df['spu'].unique())} 个SPU")
        print("✓ SPU列表:", df['spu'].unique())
        
        engine.dispose()
        print("测试完成！")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 运行主函数
    import multiprocessing
    multiprocessing.freeze_support()
    main()
