print('Python环境测试开始...')
print('Hello, world!')

# 检查基本模块
import sys
print(f'Python版本: {sys.version}')

import os
print(f'当前目录: {os.getcwd()}')

# 检查环境变量
print('环境变量:')
for key, value in os.environ.items():
    if 'SALES' in key or 'DB' in key:
        print(f'  {key}: {value}')

print('测试完成')