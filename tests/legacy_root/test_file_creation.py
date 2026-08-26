# 简单的文件创建脚本
with open('test_file.txt', 'w') as f:
    f.write('This is a test file.')

# 确认文件创建成功
import os
if os.path.exists('test_file.txt'):
    print('File created successfully!')
else:
    print('File creation failed!')