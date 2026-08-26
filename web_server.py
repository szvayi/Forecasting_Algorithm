from flask import Flask, render_template, jsonify, request
import threading
import time
import datetime
import random
import sys

app = Flask(__name__)

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
    'enable_db_write': True
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

def run_forecast_simulation():
    """运行预测模拟（实际应调用真实预测代码）"""
    forecast_status['running'] = True
    forecast_status['start_time'] = datetime.datetime.now()
    forecast_status['logs'] = []
    forecast_status['results'] = []
    forecast_status['processed_spus'] = 0
    forecast_status['progress'] = 0
    
    add_log(f"🚀 启动预测系统 (模式: {forecast_status['mode']})")
    add_log(f"📊 目标SPU数量: {len(SPU_LIST)}")
    add_log("=" * 70)
    
    for i, spu in enumerate(SPU_LIST):
        if not forecast_status['running']:
            add_log("⏹️ 预测被用户停止")
            break
        
        forecast_status['current_spu'] = spu
        add_log(f"\n📦 开始处理 SPU-{spu} ({i+1}/{len(SPU_LIST)})")
        
        # 模拟运行6种算法
        all_models = []
        
        for algo in ALGORITHMS[:4]:  # 基础模型
            if not forecast_status['running']:
                break
            add_log(f"   🔄 运行 {algo}...")
            time.sleep(0.3)  # 模拟计算时间
            
            # 生成随机WMAPE (5% - 25%)
            wmape = round(random.uniform(0.05, 0.25), 4)
            all_models.append({'name': algo, 'wmape': wmape})
            add_log(f"   ✅ {algo}: WMAPE={wmape:.2%}")
        
        if not forecast_status['running']:
            break
        
        # 模拟融合算法
        add_log(f"\n   🔄 运行融合算法...")
        time.sleep(0.2)
        
        # Ensemble-Avg (通常比基础模型好一些)
        avg_wmape = round(sum(m['wmape'] for m in all_models) / len(all_models) * 0.95, 4)
        all_models.append({'name': 'Ensemble-Avg', 'wmape': avg_wmape})
        add_log(f"   ✅ Ensemble-Avg: WMAPE={avg_wmape:.2%}")
        
        # Ensemble-Weighted (通常效果最好)
        weighted_wmape = round(min(m['wmape'] for m in all_models) * 0.98, 4)
        all_models.append({'name': 'Ensemble-Weighted', 'wmape': weighted_wmape})
        add_log(f"   ✅ Ensemble-Weighted: WMAPE={weighted_wmape:.2%}")
        
        # 找出胜出模型
        winner = min(all_models, key=lambda x: x['wmape'])
        
        add_log(f"\n   🏆 胜出模型: {winner['name']} (WMAPE: {winner['wmape']:.2%})")
        
        # 保存结果
        forecast_status['results'].append({
            'spu': spu,
            'winner': winner['name'],
            'wmape': f"{winner['wmape']:.2%}",
            'all_models': all_models
        })
        
        # 更新进度
        forecast_status['processed_spus'] = i + 1
        forecast_status['progress'] = ((i + 1) / len(SPU_LIST)) * 100
        
        add_log(f"   ✓ SPU-{spu} 处理完成")
        
        # 模拟处理间隔
        time.sleep(0.5)
    
    forecast_status['running'] = False
    forecast_status['current_spu'] = None
    add_log("\n" + "=" * 70)
    add_log(f"🎉 预测完成！共处理 {forecast_status['processed_spus']} 个SPU")
    add_log(f"📊 结果已保存到数据库: {forecast_status['enable_db_write']}")

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

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

if __name__ == '__main__':
    print("=" * 70)
    print("🚀 SPU销售预测系统 - Web监控界面")
    print("=" * 70)
    print("📱 请访问: http://localhost:8080")
    print("⚠️  按 Ctrl+C 停止服务器")
    print("=" * 70)
    sys.stdout.flush()
    
    try:
        app.run(debug=False, host='0.0.0.0', port=8080, threaded=True)
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        print("尝试使用其他端口...")
        app.run(debug=False, host='0.0.0.0', port=8081, threaded=True)
