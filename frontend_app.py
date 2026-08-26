from flask import Flask, render_template, request, jsonify
import time
import json
import os
import sys
import threading
import queue

# 添加当前目录到Python路径
sys.path.insert(0, os.path.abspath('.'))

app = Flask(__name__)

# 全局变量用于存储预测状态
forecast_status = {
    'running': False,
    'progress': 0,
    'logs': [],
    'results': None
}

# 预测队列
forecast_queue = queue.Queue()

# 模拟预测过程
def simulate_forecast():
    global forecast_status
    forecast_status['running'] = True
    forecast_status['progress'] = 0
    forecast_status['logs'] = []
    forecast_status['results'] = None
    
    # 记录开始时间
    import datetime
    start_time = datetime.datetime.now()
    forecast_status['logs'].append(f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] 开始预测任务")
    forecast_status['logs'].append("运行模式: SMART")
    forecast_status['logs'].append("目标SPU数量: 34")
    forecast_status['logs'].append("=" * 70)
    
    # 模拟处理每个SPU
    total_spus = 34
    for i in range(total_spus):
        # 模拟处理时间
        time.sleep(0.5)
        
        # 更新进度
        forecast_status['progress'] = (i + 1) / total_spus
        
        # 模拟日志输出
        current_time = datetime.datetime.now()
        forecast_status['logs'].append(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] 处理 SPU {i+1}")
        forecast_status['logs'].append("  - 模型竞赛中...")
        forecast_status['logs'].append("  - 胜出模型: LightGBM")
        import numpy as np
        forecast_status['logs'].append(f"  - WMAPE: {np.random.uniform(0.1, 0.3):.2%}")
        
        # 限制日志行数，只显示最近100行
        if len(forecast_status['logs']) > 100:
            forecast_status['logs'] = forecast_status['logs'][-100:]
    
    # 模拟完成
    time.sleep(1)
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # 模拟结果
    forecast_status['logs'].append("=" * 70)
    forecast_status['logs'].append(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 预测任务完成")
    forecast_status['logs'].append(f"总处理时间: {duration:.2f} 秒")
    forecast_status['logs'].append(f"成功处理: {total_spus}/{total_spus} 个SPU")
    
    # 模拟结果数据
    import pandas as pd
    results_data = {
        "SPU": [f"SPU-{i+1}" for i in range(10)],
        "胜出模型": ["LightGBM"] * 10,
        "WMAPE": [f"{np.random.uniform(0.1, 0.3):.2%}" for _ in range(10)],
        "预测周数": [16] * 10
    }
    results_df = pd.DataFrame(results_data)
    forecast_status['results'] = results_df.to_dict(orient='records')
    
    forecast_status['running'] = False

# 预测线程函数
def forecast_worker():
    while True:
        try:
            # 等待预测任务
            forecast_queue.get()
            # 执行预测
            simulate_forecast()
            # 标记任务完成
            forecast_queue.task_done()
        except Exception as e:
            print(f"预测线程错误: {e}")

# 启动预测线程
t = threading.Thread(target=forecast_worker, daemon=True)
t.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_forecast', methods=['POST'])
def start_forecast():
    if not forecast_status['running']:
        forecast_queue.put(None)
        return jsonify({'status': 'started'})
    else:
        return jsonify({'status': 'already_running'})

@app.route('/get_status')
def get_status():
    return jsonify({
        'running': forecast_status['running'],
        'progress': forecast_status['progress'],
        'logs': forecast_status['logs'],
        'results': forecast_status['results']
    })

# 创建templates目录和index.html文件
if not os.path.exists('templates'):
    os.makedirs('templates')

# 写入index.html文件
with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write('''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPU销售预测系统</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {
            font-family: 'Microsoft YaHei', sans-serif;
            background: #f5f7fa;
        }
        .container {
            max-width: 1200px;
            margin-top: 30px;
        }
        .card {
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 8px;
        }
        .card-header {
            background: #667eea;
            color: white;
            font-weight: bold;
        }
        .progress {
            height: 25px;
            font-size: 14px;
        }
        .log-area {
            height: 300px;
            overflow-y: auto;
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 10px;
        }
        .result-table {
            margin-top: 20px;
        }
        .btn-primary {
            background: #667eea;
            border: none;
        }
        .btn-primary:hover {
            background: #5a6fd8;
        }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 5px;
        }
        .status-running {
            background: #28a745;
        }
        .status-idle {
            background: #6c757d;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card mb-4">
            <div class="card-header">
                <h1 class="text-center">📈 SPU销售预测引擎</h1>
            </div>
            <div class="card-body">
                <div class="row mb-4">
                    <div class="col-md-6">
                        <h5>系统状态</h5>
                        <p><span class="status-indicator status-idle" id="status-indicator"></span><span id="status-text">空闲</span></p>
                    </div>
                    <div class="col-md-6 text-end">
                        <button id="start-btn" class="btn btn-primary btn-lg">开始预测</button>
                    </div>
                </div>
                
                <div class="mb-4">
                    <h5>进度</h5>
                    <div class="progress">
                        <div class="progress-bar bg-success" id="progress-bar" role="progressbar" style="width: 0%" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                            0%
                        </div>
                    </div>
                </div>
                
                <div class="mb-4">
                    <h5>运行日志</h5>
                    <div class="log-area" id="log-area">
                        等待开始...
                    </div>
                </div>
                
                <div id="results-section" style="display: none;">
                    <h5>预测结果</h5>
                    <div class="result-table">
                        <table class="table table-striped">
                            <thead>
                                <tr>
                                    <th>SPU</th>
                                    <th>胜出模型</th>
                                    <th>WMAPE</th>
                                    <th>预测周数</th>
                                </tr>
                            </thead>
                            <tbody id="results-body">
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // 启动预测
        document.getElementById('start-btn').addEventListener('click', function() {
            fetch('/start_forecast', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'started') {
                    document.getElementById('status-indicator').className = 'status-indicator status-running';
                    document.getElementById('status-text').textContent = '运行中';
                    document.getElementById('start-btn').disabled = true;
                    document.getElementById('start-btn').textContent = '预测中...';
                    document.getElementById('log-area').textContent = '开始预测...';
                    document.getElementById('results-section').style.display = 'none';
                    
                    // 开始轮询状态
                    startPolling();
                }
            });
        });
        
        // 轮询状态
        function startPolling() {
            const interval = setInterval(() => {
                fetch('/get_status')
                .then(response => response.json())
                .then(data => {
                    // 更新进度
                    const progress = Math.round(data.progress * 100);
                    document.getElementById('progress-bar').style.width = progress + '%';
                    document.getElementById('progress-bar').textContent = progress + '%';
                    document.getElementById('progress-bar').setAttribute('aria-valuenow', progress);
                    
                    // 更新日志
                    if (data.logs.length > 0) {
                        document.getElementById('log-area').textContent = data.logs.join('\n');
                        // 滚动到底部
                        const logArea = document.getElementById('log-area');
                        logArea.scrollTop = logArea.scrollHeight;
                    }
                    
                    // 更新状态
                    if (data.running) {
                        document.getElementById('status-indicator').className = 'status-indicator status-running';
                        document.getElementById('status-text').textContent = '运行中';
                    } else {
                        document.getElementById('status-indicator').className = 'status-indicator status-idle';
                        document.getElementById('status-text').textContent = '空闲';
                        document.getElementById('start-btn').disabled = false;
                        document.getElementById('start-btn').textContent = '开始预测';
                        
                        // 显示结果
                        if (data.results) {
                            document.getElementById('results-section').style.display = 'block';
                            const resultsBody = document.getElementById('results-body');
                            resultsBody.innerHTML = '';
                            
                            data.results.forEach(result => {
                                const row = document.createElement('tr');
                                row.innerHTML = `
                                    <td>${result.SPU}</td>
                                    <td>${result['胜出模型']}</td>
                                    <td>${result.WMAPE}</td>
                                    <td>${result['预测周数']}</td>
                                `;
                                resultsBody.appendChild(row);
                            });
                        }
                        
                        // 停止轮询
                        clearInterval(interval);
                    }
                });
            }, 1000);
        }
    </script>
</body>
</html>
''')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
