"""Legacy Flask compatibility entrypoint.

The active platform entrypoint is ``src.api.app``. This module is kept only as
an importable/runable compatibility surface for older local workflows.
"""

from flask import Flask, render_template, jsonify, request, send_from_directory
import threading
import time
import datetime
import random
import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text
from src.forecasting.execution_bridge import get_data_from_db, process_single_spu, save_to_database

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.config["PRIMARY_ENTRYPOINT"] = "src.api.app"
app.config["LEGACY_COMPATIBILITY_ENTRYPOINT"] = True

LEGACY_ENTRYPOINT_MESSAGE = (
    "Legacy Flask compatibility entrypoint. Use 'uvicorn src.api.app:app' "
    "for the primary platform API."
)

# 预测状态
forecast_status = {
    'running': False,
    'progress': 0,
    'current_spu': None,
    'processed_spus': 0,
    'total_spus': 34,
    'logs': [],
    'results': [],
    'start_time': None,
    'mode': 'smart',
    'enable_db_write': True,
    'prediction_data': None  # 存储预测数据
}

# 34个SPU列表
SPU_LIST = [
    '2141', '2062', '2029', '2046', '2026', '3022', '1930', '2214',
    '2033', '2038', '2208', '2012', '3050', '2176', '3033', '2192',
    '2213', '3063', '2224', '3058', '2073', '3013', '2165', '3084',
    '1976', '2197', '1476', '1533', '0887', '1577', '1750', '1512',
    '1657', '1983', '1318'
]

# 算法列表
ALGORITHMS = ['Prophet', 'XGBoost', 'LightGBM', 'AutoARIMA', 'Ensemble-Avg', 'Ensemble-Weighted']

# 数据库连接URL
DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

# 初始化日志
def setup_logging():
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/forecast_run.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def add_log(message):
    """添加日志"""
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    forecast_status['logs'].append({
        'time': timestamp,
        'message': message
    })
    # 只保留最近100条日志
    if len(forecast_status['logs']) > 100:
        forecast_status['logs'] = forecast_status['logs'][-100:]
    # 同时记录到日志文件
    logger.info(message)

def generate_fallback_prediction_data():
    """生成模拟预测数据（当真实数据获取失败时）"""
    spu_data = []
    for spu in SPU_LIST[:10]:  # 只生成前10个SPU的模拟数据
        records = []
        base_value = random.uniform(100, 1000)
        
        # 生成未来10周的预测数据
        for i in range(10):
            date = (datetime.date.today() + datetime.timedelta(weeks=i)).strftime('%Y-%m-%d')
            # 生成有趋势的预测值
            trend_factor = 1 + (i * 0.02)  # 每周增长2%
            random_factor = random.uniform(0.95, 1.05)  # 随机波动
            forecast_value = base_value * trend_factor * random_factor
            
            records.append({
                'date': date,
                'actual_value': None if i >= 2 else base_value * (i * 0.9 + 0.8),  # 前2周有实际值
                'forecast_value': round(forecast_value, 2),
                'wmape': round(random.uniform(0.03, 0.15), 4) if i < 2 else None,
                'model': random.choice(['Ensemble_Stack', 'XGBoost', 'Prophet'])
            })
        
        spu_data.append({
            'spu_id': spu,
            'name': f"产品_{spu}",
            'records': records
        })
    
    return {
        'metadata': {
            'prediction_id': f"pred_{datetime.date.today().strftime('%Y%m%d')}_001",
            'timestamp': datetime.datetime.now().isoformat(),
            'model_version': "v1.2.0",
            'data_source': "simulated",
            'total_spus': len(spu_data),
            'total_records': sum(len(spu['records']) for spu in spu_data)
        },
        'spus': spu_data
    }

def run_forecast_simulation():
    """运行真实预测（调用main.py中的函数）"""
    forecast_status['running'] = True
    forecast_status['start_time'] = datetime.datetime.now()
    forecast_status['logs'] = []
    forecast_status['results'] = []
    forecast_status['processed_spus'] = 0
    forecast_status['progress'] = 0
    forecast_status['prediction_data'] = None
    
    add_log(f"启动预测系统 (模式: {forecast_status['mode']})")
    add_log(f"目标SPU数量: {len(SPU_LIST)}")
    add_log("=" * 70)
    
    try:
        # 获取数据
        add_log("正在从数据库获取数据...")
        df_all = get_data_from_db(DB_URL)
        add_log(f"获取到 {len(df_all)} 条数据")
        
        df_all['sales'] = pd.to_numeric(df_all['sales'], errors='coerce').fillna(0)
        df_all['date'] = pd.to_datetime(df_all['date'], format='mixed')
        df_all['spu'] = df_all['spu'].astype(str)
        df_all['sku'] = df_all['sku'].astype(str)
        
        # 获取所有SPU
        all_spus = df_all['spu'].unique()
        add_log(f"发现 {len(all_spus)} 个目标 SPU")
        
        # 更新总SPU数量
        forecast_status['total_spus'] = len(all_spus)
        
        exog_cols = [c for c in df_all.columns if c in ['ad_cost', 'price']]
        if exog_cols:
            add_log(f"使用外生变量: {exog_cols}")
        
        all_res = []
        failed_spus = []
        
        # 逐个处理SPU
        for i, spu in enumerate(all_spus, 1):
            if not forecast_status['running']:
                add_log("预测被用户停止")
                break
            
            forecast_status['current_spu'] = spu
            add_log(f"[{i}/{len(all_spus)}] 处理 SPU: {spu}")
            
            try:
                # 为每个SPU准备数据
                df_spu = df_all[df_all['spu'] == spu].copy()
                res, msg, viz, profile = process_single_spu(
                    spu, df_spu, mode=forecast_status['mode'],
                    exog_cols=exog_cols, collect_viz=True, verbose=False,
                    sku_accuracy_threshold=0.01
                )
                
                if res is not None and viz is not None:
                    all_res.append(res)
                    add_log(f"  结果: {msg}")
                else:
                    failed_spus.append({'spu': spu, 'reason': msg})
                    add_log(f"  失败: {msg}")
                
                # 更新进度
                forecast_status['processed_spus'] = i
                forecast_status['progress'] = (i / len(all_spus)) * 100
                
            except Exception as e:
                failed_spus.append({'spu': spu, 'reason': str(e)})
                add_log(f"  异常: {str(e)}")
        
        # 整理结果
        if all_res:
            final = pd.concat(all_res, ignore_index=True)
            
            # 保存到数据库
            if forecast_status['enable_db_write']:
                add_log("正在保存结果到数据库...")
                save_to_database(final, DB_URL)
                add_log("结果已保存到数据库")
            
            # 生成预测数据用于前端展示
            prediction_data = generate_prediction_data_from_results(final)
            forecast_status['prediction_data'] = prediction_data
            
            # 记录统计信息
            add_log(f"\n成功: {len(all_res)}/{len(all_spus)} 个 SPU")
            if 'validation_wmape' in final.columns:
                avg_wmape = final['validation_wmape'].mean()
                add_log(f"平均WMAPE: {avg_wmape:.2%}")
        else:
            add_log("所有SPU预测失败")
            # 使用模拟数据作为fallback
            prediction_data = generate_fallback_prediction_data()
            forecast_status['prediction_data'] = prediction_data
        
        if failed_spus:
            add_log(f"\n失败 ({len(failed_spus)}):")
            for f in failed_spus[:5]:
                add_log(f"   - {f['spu']}: {f['reason']}")
        
    except Exception as e:
        add_log(f"预测过程中出现错误: {str(e)}")
        logger.error(f"预测过程中出现错误: {str(e)}")
        import traceback
        add_log(traceback.format_exc())
        # 使用模拟数据作为fallback
        prediction_data = generate_fallback_prediction_data()
        forecast_status['prediction_data'] = prediction_data
    
    forecast_status['running'] = False
    forecast_status['current_spu'] = None
    add_log("\n" + "=" * 70)
    add_log(f"预测完成！共处理 {forecast_status['processed_spus']} 个SPU")
    add_log(f"结果已保存到数据库: {forecast_status['enable_db_write']}")


def generate_prediction_data_from_results(final_df):
    """从预测结果生成前端展示数据"""
    spu_data = []
    
    # 按SPU分组
    for spu in final_df['spu'].unique():
        spu_df = final_df[final_df['spu'] == spu]
        
        records = []
        for _, row in spu_df.iterrows():
            records.append({
                'date': row['forecast_target_date'].strftime('%Y-%m-%d') if hasattr(row['forecast_target_date'], 'strftime') else str(row['forecast_target_date']),
                'actual_value': None,  # 预测数据没有实际值
                'forecast_value': round(float(row['spu_forecast_value']), 2),
                'wmape': round(float(row['validation_wmape']), 4) if 'validation_wmape' in row else None,
                'model': row['winner_algo']
            })
        
        spu_data.append({
            'spu_id': spu,
            'name': f"产品_{spu}",
            'records': records
        })
    
    return {
        'metadata': {
            'prediction_id': f"pred_{datetime.date.today().strftime('%Y%m%d')}_001",
            'timestamp': datetime.datetime.now().isoformat(),
            'model_version': "v1.2.0",
            'data_source': "real",
            'total_spus': len(spu_data),
            'total_records': sum(len(spu['records']) for spu in spu_data)
        },
        'spus': spu_data
    }

@app.route('/')
def index():
    """主页"""
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """提供静态文件"""
    return send_from_directory('.', path)

@app.route('/api/start', methods=['POST'])
def start_forecast():
    """开始预测"""
    if forecast_status['running']:
        return jsonify({'status': 'error', 'message': '预测已在运行中'})
    
    data = request.json or {}
    forecast_status['mode'] = data.get('mode', 'smart')
    forecast_status['enable_db_write'] = data.get('enable_db_write', True)
    
    # 启动预测线程
    forecast_thread = threading.Thread(target=run_forecast_simulation)
    forecast_thread.daemon = True
    forecast_thread.start()
    
    return jsonify({'status': 'success', 'message': '预测已启动'})

@app.route('/api/stop', methods=['POST'])
def stop_forecast():
    """停止预测"""
    forecast_status['running'] = False
    return jsonify({'status': 'success', 'message': '预测已停止'})

@app.route('/api/status')
def get_status():
    """获取状态"""
    elapsed = 0
    if forecast_status['start_time']:
        elapsed = (datetime.datetime.now() - forecast_status['start_time']).total_seconds()
    
    return jsonify({
        'running': forecast_status['running'],
        'progress': round(forecast_status['progress'], 1),
        'current_spu': forecast_status['current_spu'],
        'processed_spus': forecast_status['processed_spus'],
        'total_spus': forecast_status['total_spus'],
        'elapsed': round(elapsed, 1),
        'logs': forecast_status['logs'][-50:],  # 最近50条日志
        'results': forecast_status['results'][-10:],  # 最近10条结果
        'mode': forecast_status['mode']
    })

@app.route('/api/predictions/<prediction_id>')
def get_prediction_data(prediction_id):
    """获取预测数据"""
    try:
        # 如果有预测数据，直接返回
        if forecast_status['prediction_data']:
            return jsonify(forecast_status['prediction_data'])
        
        # 否则生成新的预测数据
        prediction_data = generate_fallback_prediction_data()
        return jsonify(prediction_data)
    except Exception as e:
        add_log(f"获取预测数据失败: {str(e)}")
        logger.error(f"获取预测数据失败: {str(e)}")
        # 返回模拟数据作为 fallback
        fallback_data = generate_fallback_prediction_data()
        return jsonify(fallback_data)

if __name__ == '__main__':
    # 创建logs目录
    os.makedirs('logs', exist_ok=True)
    
    print("启动SPU销售预测系统（兼容入口）...")
    print(LEGACY_ENTRYPOINT_MESSAGE)
    print("Legacy URL: http://localhost:5000")
    print("Primary API: uvicorn src.api.app:app --host 0.0.0.0 --port 8000")
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
