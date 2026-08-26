import streamlit as st
import time
import pandas as pd
import numpy as np
import os
import sys
import datetime
import json

# 跳过Streamlit欢迎提示
os.environ['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'

# 添加当前目录到Python路径
sys.path.insert(0, os.path.abspath('.'))

# 导入预测引擎
try:
    from src.forecasting.execution_bridge import main as run_forecast
    print("✅ 成功导入预测引擎")
except Exception as e:
    print(f"❌ 导入预测引擎失败: {e}")

# 页面配置
st.set_page_config(
    page_title="SPU销售预测系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 侧边栏参数设置
st.sidebar.title("预测参数")
run_mode = st.sidebar.selectbox("运行模式", ["fast", "smart", "full"], index=1)
show_plots = st.sidebar.checkbox("显示图表", True)
enable_db_write = st.sidebar.checkbox("写入数据库", True)

# 主界面
st.title("SPU销售预测引擎")
st.write("实时监控预测过程和结果")

# 状态显示区域
status_container = st.empty()
progress_container = st.empty()
log_container = st.empty()
results_container = st.empty()

# 运行按钮
if st.button("开始预测", key="run_forecast"):
    # 清空之前的输出
    status_container.empty()
    progress_container.empty()
    log_container.empty()
    results_container.empty()
    
    # 显示开始信息
    status_container.info("🚀 开始预测...")
    
    # 创建进度条
    progress_bar = progress_container.progress(0)
    
    # 创建日志区域
    log_area = log_container.text_area("运行日志", height=300)
    
    # 模拟预测过程（实际部署时替换为真实的run_forecast调用）
    total_spus = 34
    log_messages = []
    
    # 记录开始时间
    start_time = datetime.datetime.now()
    log_messages.append(f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] 开始预测任务")
    log_messages.append(f"运行模式: {run_mode.upper()}")
    log_messages.append(f"目标SPU数量: {total_spus}")
    log_messages.append("=" * 70)
    
    # 更新日志
    log_area.text("\n".join(log_messages))
    
    # 模拟处理每个SPU
    for i in range(total_spus):
        # 模拟处理时间
        time.sleep(0.5)
        
        # 更新进度
        progress = (i + 1) / total_spus
        progress_bar.progress(progress)
        
        # 更新状态
        status_container.info(f"处理中: SPU {i+1}/{total_spus}")
        
        # 模拟日志输出
        current_time = datetime.datetime.now()
        log_messages.append(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] 处理 SPU {i+1}")
        log_messages.append(f"  - 模型竞赛中...")
        log_messages.append(f"  - 胜出模型: LightGBM")
        log_messages.append(f"  - WMAPE: {np.random.uniform(0.1, 0.3):.2%}")
        
        # 限制日志行数，只显示最近100行
        if len(log_messages) > 100:
            log_messages = log_messages[-100:]
        
        # 更新日志
        log_area.text("\n".join(log_messages))
    
    # 模拟完成
    time.sleep(1)
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # 更新状态
    status_container.success("✅ 预测完成！")
    progress_bar.progress(1.0)
    
    # 模拟结果
    log_messages.append("=" * 70)
    log_messages.append(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 预测任务完成")
    log_messages.append(f"总处理时间: {duration:.2f} 秒")
    log_messages.append(f"成功处理: {total_spus}/{total_spus} 个SPU")
    log_area.text("\n".join(log_messages))
    
    # 显示结果摘要
    with results_container:
        st.subheader("预测结果摘要")
        
        # 模拟结果数据
        results_data = {
            "SPU": [f"SPU-{i+1}" for i in range(10)],
            "胜出模型": ["LightGBM"] * 10,
            "WMAPE": [f"{np.random.uniform(0.1, 0.3):.2%}" for _ in range(10)],
            "预测周数": [16] * 10
        }
        
        results_df = pd.DataFrame(results_data)
        st.dataframe(results_df, use_container_width=True)
        
        # 显示统计信息
        st.write(f"**总计:**")
        st.write(f"- 处理SPU数量: {total_spus}")
        st.write(f"- 平均准确率: {np.random.uniform(0.15, 0.25):.2%}")
        st.write(f"- 总处理时间: {duration:.2f} 秒")

# 页面底部信息
st.sidebar.markdown("---")
st.sidebar.markdown("**关于系统**")
st.sidebar.markdown("SPU销售预测引擎 v8.4")
st.sidebar.markdown("基于多模型竞赛的智能预测系统")
st.sidebar.markdown("支持Prophet、XGBoost、LightGBM等多种算法")
