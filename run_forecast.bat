@echo off

rem 设置Python解释器路径
set PYTHON_EXE=C:\Users\VY0814\Forecasting_Algorithm\.venv\Scripts\python.exe

rem 运行预测脚本
echo 开始执行预测...
%PYTHON_EXE% run_forecast.py

echo 预测执行完成！
pause
