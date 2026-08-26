"""
测试脚本 - 用于测试新版本功能
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


def test_new_features():
    """测试新版本功能"""
    print("=" * 70)
    print("🧪 新版本功能测试")
    print("=" * 70)
    
    # 从环境变量获取数据库URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # 1. 测试增强日志记录器
    print("\n1️⃣ 测试增强日志记录器...")
    enhanced_logger = EnhancedLogger(log_dir='logs', log_level='INFO')
    enhanced_logger.log_forecast_start(spu='SPU001', mode='smart', exog_cols=['ad_cost', 'price'])
    enhanced_logger.log_data_quality(spu='SPU001', data_points=100, missing_rate=0.05, trend='upward', seasonality='strong')
    enhanced_logger.log_model_selection(spu='SPU001', models=[
        {'algo': 'Prophet', 'wmape': 0.15, 'mape': 0.12, 'mae': 50.2},
        {'algo': 'XGBoost', 'wmape': 0.18, 'mape': 0.15, 'mae': 55.3},
        {'algo': 'LightGBM', 'wmape': 0.16, 'mape': 0.13, 'mae': 52.1}
    ])
    enhanced_logger.log_forecast_end(spu='SPU001', elapsed_time=12.5, wmape=0.15, algo='Prophet')
    print("✅ 增强日志记录器测试完成")
    
    # 2. 测试告警管理器
    print("\n2️⃣ 测试告警管理器...")
    alert_manager = AlertManager()
    alert = alert_manager.create_alert(
        alert_type='WMAPE_THRESHOLD_EXCEEDED',
        spu='SPU001',
        severity='HIGH',
        message='SPU SPU001 WMAPE超过阈值',
        details={'wmape': 0.45, 'threshold': 0.30}
    )
    summary = alert_manager.get_alert_summary()
    print(f"   告警摘要: {summary}")
    print("✅ 告警管理器测试完成")
    
    # 3. 测试误差报警管理器
    print("\n3️⃣ 测试误差报警管理器...")
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
    print(f"   误差报警报告: 告警数量={report['summary']['total_alerts']}")
    print("✅ 误差报警管理器测试完成")
    
    # 4. 测试SKU准确性评估优化
    print("\n4️⃣ 测试SKU准确性评估优化...")
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
    print(f"   SKU准确性评估结果: WMAPE={result['wmape']:.2%}, SKU数量={result['sku_count']}")
    print("✅ SKU准确性评估优化测试完成")
    
    # 5. 测试交互式图表生成器
    print("\n5️⃣ 测试交互式图表生成器...")
    generator = InteractiveChartGenerator(save_dir='D:/华熠/plots')
    
    # 生成示例数据
    train = pd.Series(np.random.randint(100, 1000, 80), index=dates[:80])
    test = pd.Series(np.random.randint(100, 1000, 10), index=dates[80:90])
    future = np.random.randint(100, 1000, 10)
    future_dates = dates[90:100]
    results = [
        {'name': 'Prophet', 'wmape': 0.15, 'preds': np.random.randint(100, 1000, 10)},
        {'name': 'XGBoost', 'wmape': 0.18, 'preds': np.random.randint(100, 1000, 10)},
        {'name': 'LightGBM', 'wmape': 0.16, 'preds': np.random.randint(100, 1000, 10)}
    ]
    sku_future_df = pd.DataFrame({
        'SKU001': np.random.randint(10, 100, 10),
        'SKU002': np.random.randint(20, 200, 10),
        'SKU003': np.random.randint(15, 150, 10)
    }, index=future_dates)
    
    # 创建简单的profile对象
    profile = SPUProfiler(verbose=False).analyze('SPU001', train, train, None)
    profile.winner_wmape = 0.15
    profile.winner_algo = 'Prophet'
    
    # 生成图表（不显示）
    fig = generator.generate_forecast_chart(
        profile=profile, train=train, test=test, results=results, 
        future=future, future_dates=future_dates, sku_future_df=sku_future_df,
        save_path='D:/华熠/plots/test_forecast.html', show_plot=False
    )
    print("   交互式图表已生成（HTML格式）")
    print("✅ 交互式图表生成器测试完成")
    
    # 6. 测试数据库优化器
    print("\n6️⃣ 测试数据库优化器...")
    db_optimizer = DatabaseOptimizer(db_url=DB_URL, pool_size=10, max_overflow=20)
    results = db_optimizer.run_optimization(table_name='sales_forecast_history', schema='finedatalink')
    print(f"   数据库优化完成: 索引创建={results['indexes']['indexes_created']}")
    print("✅ 数据库优化器测试完成")
    
    # 7. 测试监控模块
    print("\n7️⃣ 测试监控模块...")
    monitor = ForecastingMonitor(db_url=DB_URL, wmape_threshold=0.30)
    print("   监控模块初始化成功")
    print("✅ 监控模块测试完成")
    
    print("\n" + "=" * 70)
    print("✅ 所有新版本功能测试完成!")
    print("=" * 70)


def test_with_sample_data():
    """使用示例数据测试完整流程"""
    print("\n" + "=" * 70)
    print("🧪 使用示例数据测试完整流程")
    print("=" * 70)
    
    # 从环境变量获取数据库URL
    DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
    
    # 创建示例数据
    dates = pd.date_range('2026-01-01', periods=100, freq='W')
    
    # SPU数据
    spu_data = []
    for date in dates:
        spu_data.append({
            'date': date,
            'spu': 'SPU001',
            'sales': np.random.randint(100, 1000),
            'price': np.random.uniform(10, 50),
            'ad_cost': np.random.uniform(100, 500)
        })
    
    # SKU数据
    sku_data = []
    for date in dates:
        for sku in ['SKU001', 'SKU002', 'SKU003']:
            sku_data.append({
                'date': date,
                'spu': 'SPU001',
                'sku': sku,
                'sales': np.random.randint(10, 100),
                'price': np.random.uniform(10, 50)
            })
    
    df_all = pd.DataFrame(sku_data + spu_data)
    
    print(f"✅ 示例数据已生成: {len(df_all)} 行记录")
    
    # 处理SPU预测
    spu = 'SPU001'
    print(f"\n🔄 处理 SPU: {spu}")
    
    t0 = time.time()
    res, msg, viz, profile = process_single_spu(
        spu, df_all, mode='smart',
        exog_cols=['ad_cost', 'price'], collect_viz=True, verbose=True
    )
    print(f"\n   📝 结果: {msg}")
    print(f"   ⏱️ 耗时: {time.time() - t0:.2f}秒")
    
    if res is not None and viz is not None:
        print("\n✅ 预测成功!")
        
        # 保存结果
        SAVE_PLOT_DIR = 'D:/华熠/plots'
        OUTPUT_DIR = 'D:/华熠/output'
        
        os.makedirs(SAVE_PLOT_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # 保存图表
        best_save_path = os.path.join(SAVE_PLOT_DIR, f"BEST_{spu}.png")
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
        
        # 保存CSV
        output_file = os.path.join(OUTPUT_DIR, f'spu_forecast_{datetime.date.today()}.csv')
        res.to_csv(output_file, index=False)
        print(f"   📄 CSV已保存至: {output_file}")
        
        # 保存JSON报告
        REPORT_DIR = 'D:/华熠/reports'
        os.makedirs(REPORT_DIR, exist_ok=True)
        report_file = os.path.join(REPORT_DIR, f'spu_profiles_{datetime.date.today()}.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump([profile.to_dict()], f, ensure_ascii=False, indent=2, default=str)
        print(f"   📄 模型报告已保存至: {report_file}")
        
        # 写入数据库
        if True:  # ENABLE_DB_WRITE
            save_to_database(res, DB_URL)
            print("   💾 数据库写入成功")
        
        return res, msg, viz, profile
    else:
        print(f"\n❌ 预测失败: {msg}")
        return None, msg, None, None


def main():
    """主函数"""
    # 测试新版本功能
    test_new_features()
    
    # 测试完整流程
    test_with_sample_data()
    
    print("\n" + "=" * 70)
    print("✅ 所有测试完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
