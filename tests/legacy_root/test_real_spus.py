"""
实操测试脚本 - 使用真实SPU对象进行测试
"""

import os
import datetime
import time
import pandas as pd
import numpy as np
import json
from sqlalchemy import create_engine, text
from src.forecasting.models import *
from src.forecasting.predictors import *
from src.forecasting.monitor import ForecastingMonitor
from src.forecasting.logging_alert import EnhancedLogger, AlertManager
from src.forecasting.error_alert import ErrorAlertManager
from src.forecasting.sku_accuracy_optimized import calculate_sku_accuracy_optimized
from src.forecasting.interactive_charts import InteractiveChartGenerator
from src.database.repositories import save_to_database
from src.database.optimization import DatabaseOptimizer


def test_with_real_spus():
    """使用真实SPU对象进行测试"""
    print("=" * 70)
    print("🧪 使用真实SPU对象进行实操测试")
    print("=" * 70)
    
    # 从环境变量获取数据库URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # 创建数据库引擎
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    try:
        with engine.connect() as conn:
            # 获取SPU列表
            spu_query = text("""
                SELECT '2141' AS SPU 
                UNION ALL 
                SELECT '2062'
            """)
            spu_result = conn.execute(spu_query)
            spu_list = [row[0] for row in spu_result.fetchall()]
            print(f"\n✅ 找到 {len(spu_list)} 个目标 SPU: {spu_list}")
            
            # 获取数据
            data_query = text("""
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
                ),
                SPU_list as (
                    SELECT '2141' AS SPU 
                    UNION ALL 
                    SELECT '2062' 
                )
                select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
                       ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
                from base 
                where 1=1 and SPU in (select * from SPU_list)
                group by report_date, SPU, local_sku
                order by report_date
            """)
            
            t0 = time.time()
            df = pd.read_sql(data_query, con=conn)
            df.columns = [col.lower() for col in df.columns]
            print(f"✅ 数据获取完成！共加载 {len(df)} 行记录，耗时: {time.time() - t0:.1f} 秒")
            
            # 数据预处理
            df['sales'] = pd.to_numeric(df['sales'], errors='coerce').fillna(0)
            df['date'] = pd.to_datetime(df['date'], format='mixed')
            df['spu'] = df['spu'].astype(str)
            df['sku'] = df['sku'].astype(str)
            
            # 处理每个SPU
            SAVE_PLOT_DIR = 'D:/华熠/plots'
            OUTPUT_DIR = 'D:/华熠/output'
            REPORT_DIR = 'D:/华熠/reports'
            
            os.makedirs(SAVE_PLOT_DIR, exist_ok=True)
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            os.makedirs(REPORT_DIR, exist_ok=True)
            
            RUN_MODE = 'smart'
            SHOW_PLOTS = False  # 不显示图表，只保存
            SAVE_PLOTS = True
            ENABLE_DB_WRITE = True
            
            global_best_wmape, global_best_viz = float('inf'), None
            all_res, failed_spus, all_reports = [], [], []
            profiler = SPUProfiler()
            
            for i, spu in enumerate(spu_list, 1):
                print(f"\n{'=' * 70}\n[{i}/{len(spu_list)}] 处理 SPU: {spu}\n{'=' * 70}")
                
                # 处理SPU预测
                t0 = time.time()
                res, msg, viz, profile = process_single_spu(
                    spu, df, mode=RUN_MODE,
                    exog_cols=['ad_cost', 'price'], collect_viz=True, verbose=True
                )
                print(f"\n   📝 结果: {msg}")
                print(f"   ⏱️ 耗时: {time.time() - t0:.2f}秒")
                
                if res is not None and viz is not None:
                    all_res.append(res)
                    if profile.winner_wmape < global_best_wmape:
                        global_best_wmape, global_best_viz = profile.winner_wmape, viz
                        print(f"   🌟 当前暂列第一! WMAPE: {global_best_wmape:.2%}")
                    all_reports.append(profiler.generate_report_dict(profile))
                    
                    # 保存图表
                    best_save_path = os.path.join(SAVE_PLOT_DIR, f"BEST_{spu}.png") if SAVE_PLOTS else None
                    plot_best_spu_style(
                        viz['profile'],
                        viz['train'],
                        viz['test'],
                        viz['results'],
                        viz['future'],
                        viz['dates'],
                        sku_future_df=viz.get('sku_future_df'),
                        save_path=best_save_path,
                        show_plot=False
                    )
                    print(f"   📊 图表已保存至: {best_save_path}")
                else:
                    failed_spus.append({'spu': spu, 'reason': msg})
            
            print("\n" + "=" * 70 + "\n📊 批量处理完成!\n" + "=" * 70)
            
            # 保存结果
            if all_res:
                final = pd.concat(all_res, ignore_index=True)
                print(f"\n✅ 成功: {len(all_res)}/{len(spu_list)} 个 SPU")
                
                print("\n🏆 胜出模型统计:")
                print(final.groupby('winner_algo')['spu'].nunique().sort_values(ascending=False).to_string())
                
                # 保存CSV
                output_file = os.path.join(OUTPUT_DIR, f'spu_forecast_{datetime.date.today()}.csv')
                final.to_csv(output_file, index=False)
                print(f"\n   📄 CSV 已保存至: {output_file}")
                
                # 保存JSON报告
                report_file = os.path.join(REPORT_DIR, f'spu_profiles_{datetime.date.today()}.json')
                with open(report_file, 'w', encoding='utf-8') as f:
                    json.dump(all_reports, f, ensure_ascii=False, indent=2, default=str)
                print(f"   📄 模型报告已保存至: {report_file}")
                
                # 写入数据库
                if ENABLE_DB_WRITE:
                    save_to_database(final, DB_URL)
                    print("   💾 数据库写入成功")
            
            if failed_spus:
                print(f"\n⚠️ 失败 ({len(failed_spus)}):")
                for f in failed_spus[:5]:
                    print(f"   - {f['spu']}: {f['reason']}")
            
            # 生成交互式图表
            if global_best_viz:
                best_spu = global_best_viz['profile'].spu
                print(f"\n🌟 正在生成全场最佳 SPU 交互式图表: {best_spu} (WMAPE: {global_best_wmape:.2%})")
                
                generator = InteractiveChartGenerator(save_dir=SAVE_PLOT_DIR)
                
                # 生成交互式图表
                fig = generator.generate_forecast_chart(
                    profile=global_best_viz['profile'],
                    train=global_best_viz['train'],
                    test=global_best_viz['test'],
                    results=global_best_viz['results'],
                    future=global_best_viz['future'],
                    future_dates=global_best_viz['dates'],
                    sku_future_df=global_best_viz.get('sku_future_df'),
                    save_path=os.path.join(SAVE_PLOT_DIR, f"BEST_{best_spu}_interactive.html"),
                    show_plot=False
                )
                print(f"   📊 交互式图表已生成: BEST_{best_spu}_interactive.html")
                
                # 生成SKU份额图表
                if global_best_viz.get('sku_future_df') is not None and not global_best_viz['sku_future_df'].empty:
                    fig_sku = generator.generate_sku_share_chart(
                        sku_shares_df=global_best_viz['sku_future_df'],
                        save_path=os.path.join(SAVE_PLOT_DIR, f"BEST_{best_spu}_sku_shares.html"),
                        show_plot=False
                    )
                    print(f"   📊 SKU份额图表已生成: BEST_{best_spu}_sku_shares.html")
            
            # 测试监控模块
            print("\n" + "=" * 70)
            print("🧪 测试监控模块")
            print("=" * 70)
            
            monitor = ForecastingMonitor(db_url=DB_URL, wmape_threshold=0.30)
            print("✅ 监控模块初始化成功")
            
            # 测试告警管理器
            alert_manager = AlertManager()
            alert = alert_manager.create_alert(
                alert_type='WMAPE_THRESHOLD_EXCEEDED',
                spu='SPU001',
                severity='HIGH',
                message='SPU SPU001 WMAPE超过阈值',
                details={'wmape': 0.45, 'threshold': 0.30}
            )
            summary = alert_manager.get_alert_summary()
            print(f"✅ 告警管理器测试完成: {summary}")
            
            # 测试误差报警管理器
            error_alert_manager = ErrorAlertManager(db_url=DB_URL, wmape_threshold=0.30)
            spu = 'SPU001'
            wmape = 0.45
            historical_wmapes = [0.15, 0.18, 0.20, 0.22, 0.25]
            sku_metrics = {
                'SKU001': {'wmape': 0.12, 'total_sales': 1000, 'weight_in_spu': 0.3},
                'SKU002': {'wmape': 0.48, 'total_sales': 1500, 'weight_in_spu': 0.4},
                'SKU003': {'wmape': 0.18, 'total_sales': 1200, 'weight_in_spu': 0.3}
            }
            model_results = [
                {'algo': 'Prophet', 'wmape': 0.15, 'mape': 0.12, 'mae': 50.2},
                {'algo': 'XGBoost', 'wmape': 0.48, 'mape': 0.45, 'mae': 120.3},
                {'algo': 'LightGBM', 'wmape': 0.20, 'mape': 0.18, 'mae': 60.1}
            ]
            report = error_alert_manager.run_error_alerts(spu, wmape, historical_wmapes, sku_metrics, model_results)
            print(f"✅ 误差报警管理器测试完成: 告警数量={report['summary']['total_alerts']}")
            
            # 测试SKU准确性评估优化
            dates = pd.date_range('2026-01-01', periods=10, freq='W')
            actual = pd.DataFrame({
                'SKU001': np.random.randint(10, 100, 10),
                'SKU002': np.random.randint(20, 200, 10),
                'SKU003': np.random.randint(15, 150, 10)
            }, index=dates)
            pred = pd.DataFrame({
                'SKU001': np.random.randint(10, 100, 10) + np.random.randint(-10, 10, 10),
                'SKU002': np.random.randint(20, 200, 10) + np.random.randint(-20, 20, 10),
                'SKU003': np.random.randint(15, 150, 10) + np.random.randint(-15, 15, 10)
            }, index=dates)
            result = calculate_sku_accuracy_optimized(actual, pred, threshold=0.01)
            print(f"✅ SKU准确性评估优化测试完成: WMAPE={result['wmape']:.2%}, SKU数量={result['sku_count']}")
            
            # 测试数据库优化器
            db_optimizer = DatabaseOptimizer(db_url=DB_URL, pool_size=10, max_overflow=20)
            results = db_optimizer.run_optimization(table_name='sales_forecast_history', schema='finedatalink')
            print(f"✅ 数据库优化器测试完成: 索引创建={results['indexes']['indexes_created']}")
            
            print("\n" + "=" * 70)
            print("✅ 所有实操测试完成!")
            print("=" * 70)
            
            return all_res, failed_spus, global_best_viz
            
    finally:
        engine.dispose()


def main():
    """主函数"""
    test_with_real_spus()


if __name__ == "__main__":
    main()
