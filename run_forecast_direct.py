import sys
import os
import datetime

sys.path.insert(0, '.')
os.chdir(r'C:\Users\VY0814\Forecasting_Algorithm')

from src.forecasting.execution_bridge import main

print("开始执行预测...")
print(f"当前时间: {datetime.datetime.now()}")

try:
    main()
    print(f"预测执行完成: {datetime.datetime.now()}")
except Exception as e:
    print(f"预测执行失败: {e}")
    import traceback
    traceback.print_exc()
