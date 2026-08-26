#!/usr/bin/env python3
"""
测试Python环境
"""
print("Python版本:")
import sys
print(sys.version)

print("\n当前目录:")
import os
print(os.getcwd())

print("\n尝试导入FastAPI:")
try:
    import fastapi
    print(f"FastAPI版本: {fastapi.__version__}")
except Exception as e:
    print(f"导入FastAPI失败: {e}")

print("\n尝试导入uvicorn:")
try:
    import uvicorn
    print(f"Uvicorn版本: {uvicorn.__version__}")
except Exception as e:
    print(f"导入uvicorn失败: {e}")

print("\n尝试导入pandas:")
try:
    import pandas
    print(f"Pandas版本: {pandas.__version__}")
except Exception as e:
    print(f"导入pandas失败: {e}")

print("\n测试完成")
