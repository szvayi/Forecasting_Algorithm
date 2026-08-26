import os
import sys

# 写入到文件
with open('test_output.txt', 'w') as f:
    f.write(f'Current directory: {os.getcwd()}\n')
    f.write(f'Python version: {sys.version}\n')
    f.write('Hello, World!\n')

print('Output written to test_output.txt')