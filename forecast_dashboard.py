"""
SPU销售预测系统 - 可视化仪表板
类似Python运行界面的实时预测监控
"""
import sys
import os
import datetime
import io
import time
import threading
import queue

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 全局状态
forecast_status = {
    'running': False,
    'progress': 0,
    'current_spu': '',
    'logs': [],
    'results': [],
    'start_time': None,
    'total_spus': 34,
    'processed_spus': 0
}

log_queue = queue.Queue()

def add_log(message):
    """添加日志"""
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    forecast_status['logs'].append(log_entry)
    log_queue.put(log_entry)
    # 限制日志数量
    if len(forecast_status['logs']) > 200:
        forecast_status['logs'] = forecast_status['logs'][-200:]

def update_progress(current, total):
    """更新进度"""
    forecast_status['progress'] = current / total if total > 0 else 0
    forecast_status['processed_spus'] = current

def print_dashboard():
    """打印仪表板"""
    # 清屏
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # 标题
    print("=" * 80)
    print("📈 SPU销售预测系统 - 实时监控仪表板")
    print("=" * 80)
    
    # 基本信息
    if forecast_status['start_time']:
        elapsed = (datetime.datetime.now() - forecast_status['start_time']).total_seconds()
        print(f"⏱️  运行时间: {elapsed:.1f}秒  |  模式: SMART  |  目标SPU: {forecast_status['total_spus']}个")
    else:
        print(f"⏱️  等待开始...  |  模式: SMART  |  目标SPU: {forecast_status['total_spus']}个")
    
    print("-" * 80)
    
    # 状态栏
    status = "🟢 运行中" if forecast_status['running'] else "🔴 已停止"
    current = forecast_status['current_spu']
    print(f"状态: {status}  |  当前处理: {current if current else '等待中...'}")
    
    # 进度条
    progress = forecast_status['progress']
    bar_length = 50
    filled = int(progress * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    print(f"进度: [{bar}] {progress*100:.1f}% ({forecast_status['processed_spus']}/{forecast_status['total_spus']})")
    
    print("-" * 80)
    
    # 日志区域 - 显示最近15条
    print("📋 实时日志:")
    print("-" * 80)
    logs_to_show = forecast_status['logs'][-15:]
    for log in logs_to_show:
        print(log)
    print("-" * 80)
    
    # 统计信息
    if forecast_status['results']:
        print(f"📊 已完成: {len(forecast_status['results'])}个SPU  |  最近: {forecast_status['results'][-1] if forecast_status['results'] else '无'}")
    
    print("=" * 80)

def run_forecast_simulation():
    """运行预测模拟（实际使用时替换为真实预测）"""
    forecast_status['running'] = True
    forecast_status['start_time'] = datetime.datetime.now()
    
    add_log("🚀 启动SPU销售预测引擎")
    add_log("📊 运行模式: SMART")
    add_log("🎯 目标SPU数量: 34个")
    add_log("=" * 70)
    
    # 模拟数据获取
    add_log("🔄 正在连接数据库...")
    time.sleep(1)
    add_log("✅ 数据库连接成功")
    add_log("🔄 正在拉取训练数据...")
    time.sleep(2)
    add_log("✅ 数据加载完成，共发现34个目标SPU")
    add_log("")
    
    # 模拟处理每个SPU
    total = forecast_status['total_spus']
    for i in range(1, total + 1):
        if not forecast_status['running']:
            break
        
        spu_id = f"SPU-{i:04d}"
        forecast_status['current_spu'] = spu_id
        
        add_log(f"[{i}/{total}] 🔄 开始处理 {spu_id}")
        
        # 模拟处理步骤
        time.sleep(0.3)
        add_log(f"      📊 数据预处理完成")
        
        time.sleep(0.2)
        add_log(f"      🤖 启动模型竞赛...")
        
        time.sleep(0.5)
        models = ['Prophet', 'XGBoost', 'LightGBM', 'AutoARIMA']
        for model in models:
            wmape = 0.1 + (i % 10) * 0.02
            add_log(f"      ✅ {model}: WMAPE={wmape:.2%}")
        
        time.sleep(0.2)
        winner = 'LightGBM' if i % 3 == 0 else 'XGBoost'
        add_log(f"      🏆 胜出模型: {winner}")
        
        time.sleep(0.2)
        add_log(f"      📝 生成预测结果 (16周)")
        
        # 更新结果
        forecast_status['results'].append(f"{spu_id}:{winner}")
        
        # 更新进度
        update_progress(i, total)
        
        # 更新显示
        print_dashboard()
        
        add_log("")
    
    # 完成
    if forecast_status['running']:
        add_log("=" * 70)
        add_log("🎉 预测任务完成!")
        add_log(f"✅ 成功处理: {forecast_status['processed_spus']}/{total}个SPU")
        elapsed = (datetime.datetime.now() - forecast_status['start_time']).total_seconds()
        add_log(f"⏱️  总耗时: {elapsed:.1f}秒")
        add_log("💾 结果已保存至数据库")
        forecast_status['running'] = False
        forecast_status['current_spu'] = ''
        print_dashboard()

def run_real_forecast():
    """运行真实预测（集成main.py）"""
    forecast_status['running'] = True
    forecast_status['start_time'] = datetime.datetime.now()
    
    add_log("🚀 启动SPU销售预测引擎")
    add_log("📊 运行模式: SMART")
    add_log("🎯 目标SPU数量: 34个")
    add_log("=" * 70)
    
    try:
        # 添加路径
        sys.path.insert(0, '.')
        from src.forecasting.execution_bridge import main as forecast_main
        
        # 重定向输出到日志
        class LogCapture:
            def __init__(self):
                self.buffer = ""
            def write(self, text):
                if text.strip():
                    add_log(text.strip())
                self.buffer += text
            def flush(self):
                pass
        
        # 保存原始输出
        original_stdout = sys.stdout
        sys.stdout = LogCapture()
        
        # 运行预测
        forecast_main()
        
        # 恢复输出
        sys.stdout = original_stdout
        
        add_log("=" * 70)
        add_log("🎉 预测任务完成!")
        forecast_status['running'] = False
        
    except Exception as e:
        sys.stdout = original_stdout if 'original_stdout' in dir() else sys.stdout
        add_log(f"❌ 预测失败: {str(e)}")
        import traceback
        add_log(traceback.format_exc())
        forecast_status['running'] = False
    
    print_dashboard()

def main():
    """主函数"""
    print("欢迎使用SPU销售预测系统")
    print("-" * 80)
    print("1. 开始预测 (实时监控模式)")
    print("2. 退出")
    print("-" * 80)
    
    choice = input("请选择: ").strip()
    
    if choice == '1':
        # 启动预测线程
        forecast_thread = threading.Thread(target=run_forecast_simulation)
        forecast_thread.daemon = True
        forecast_thread.start()
        
        # 主线程显示仪表板
        try:
            while forecast_status['running'] or forecast_status['logs']:
                print_dashboard()
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n⚠️ 用户中断预测")
            forecast_status['running'] = False
        
        print("\n按任意键退出...")
        input()
        
    elif choice == '2':
        print("退出系统...")
    else:
        print("无效选择")
        time.sleep(1)
        main()

if __name__ == '__main__':
    main()
