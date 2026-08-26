#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
监控预测执行进度
"""

import os
import sys
import datetime
import time

print("=" * 80)
print("📊 预测执行进度监控")
print("=" * 80)

# 检查日志文件
log_file = f"logs/forecast_run_{datetime.date.today().strftime('%Y%m%d')}.log"

if not os.path.exists(log_file):
    print(f"❌ 日志文件不存在: {log_file}")
    print("请确认预测程序是否已启动")
    sys.exit(1)

print(f"📁 监控日志文件: {log_file}")
print("\n⏳ 正在监控执行进度...")
print("-" * 80)

# 读取日志文件的最后几行
def read_last_lines(filename, n=50):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-n:] if len(lines) > n else lines
    except Exception as e:
        return [f"Error reading file: {e}"]

# 解析进度信息
def parse_progress(lines):
    spu_count = 0
    total_spus = 34  # 目标SPU数量
    
    for line in lines:
        # 查找SPU处理相关的日志
        if "处理 SPU:" in line or "SPU:" in line:
            spu_count += 1
        # 查找完成信息
        if "批量处理完成" in line or "成功:" in line:
            # 尝试提取成功数量
            import re
            match = re.search(r'成功:\s*(\d+)', line)
            if match:
                spu_count = int(match.group(1))
    
    return spu_count, total_spus

# 监控循环
last_progress = -1
try:
    while True:
        lines = read_last_lines(log_file, 100)
        current_spu, total_spus = parse_progress(lines)
        
        if total_spus > 0:
            progress = (current_spu / total_spus) * 100
            
            # 每20%通知一次
            milestones = [20, 40, 60, 80, 100]
            for milestone in milestones:
                if last_progress < milestone <= progress:
                    print(f"\n🎯 进度更新: {milestone}% 完成 ({current_spu}/{total_spus} SPU)")
                    print(f"   时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    last_progress = milestone
                    break
        
        # 检查是否完成
        for line in lines:
            if "数据库写入成功" in line or "预测完成" in line:
                print(f"\n✅ 预测执行完成！")
                print(f"   完成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                sys.exit(0)
        
        # 检查是否有错误
        for line in lines:
            if "严重错误" in line or "Error" in line or "Exception" in line:
                print(f"\n❌ 发现错误:")
                print(f"   {line.strip()}")
        
        time.sleep(30)  # 每30秒检查一次
        
except KeyboardInterrupt:
    print("\n\n监控已停止")
    sys.exit(0)
