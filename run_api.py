import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("正在启动API服务...")

try:
    import uvicorn
    print("Uvicorn已导入")
    print("启动服务器...")
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000)
except Exception as e:
    print(f"启动失败: {e}")
    import traceback
    traceback.print_exc()
