#!/usr/bin/env python3
"""测试analysis_worker.py的执行并捕获详细错误"""
import os
import sys
import subprocess
import traceback

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"
MODE = "smart"

worker_script = os.path.join(os.path.dirname(__file__), 'src/api/analysis_worker.py')
cmd = [sys.executable, worker_script, DB_URL, MODE]

print(f"执行命令: {' '.join(cmd)}")
print("=" * 70)

try:
    # 执行命令并捕获所有输出
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=os.path.abspath(os.path.dirname(__file__))
    )
    
    print("STDOUT:")
    print(result.stdout)
    print("=" * 70)
    print("STDERR:")
    print(result.stderr)
    print("=" * 70)
    print(f"返回码: {result.returncode}")
    
except Exception as e:
    print(f"执行失败: {str(e)}")
    traceback.print_exc()
