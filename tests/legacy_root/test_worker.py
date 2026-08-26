#!/usr/bin/env python3
"""测试analysis_worker.py的执行"""
import os
import sys
import subprocess

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

worker_script = os.path.join(os.path.dirname(__file__), 'src/api/analysis_worker.py')
cmd = [sys.executable, worker_script, DB_URL]

print(f"执行命令: {' '.join(cmd)}")
print("=" * 70)

# 执行命令并实时输出
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,  # 合并stderr到stdout
    text=True,
    bufsize=1,  # 行缓冲
    cwd=os.path.abspath(os.path.dirname(__file__))
)

# 实时读取输出
for line in process.stdout:
    print(line, end='')

# 等待进程结束
process.wait()
print("=" * 70)
print(f"进程退出码: {process.returncode}")
