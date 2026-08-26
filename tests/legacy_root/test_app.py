#!/usr/bin/env python3
"""
测试 Flask 应用
"""
import sys
import os

# 重定向输出到文件
with open('app_test_output.txt', 'w', encoding='utf-8') as f:
    sys.stdout = f
    sys.stderr = f
    
    try:
        print("开始测试 Flask 应用...")
        from app import app
        print("✓ Flask 应用导入成功")
        
        # 测试应用配置
        print(f"调试模式: {app.debug}")
        print(f"应用名称: {app.name}")
        
        # 测试路由
        print("\n注册的路由:")
        for rule in app.url_map.iter_rules():
            print(f"  {rule.endpoint}: {rule.rule}")
        
        print("\n测试完成!")
        
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()

# 恢复标准输出
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print("测试已完成，输出已保存到 app_test_output.txt 文件中")
