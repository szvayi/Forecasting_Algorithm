#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
简单的Python环境测试
"""

print("Hello, World!")
print("Python is working!")

import os
import sys
print(f"Python version: {sys.version}")
print(f"Current directory: {os.getcwd()}")
print(f"Python path: {sys.path}")

# 测试导入基本模块
try:
    import pandas
    print("✅ pandas module imported successfully")
except ImportError:
    print("❌ pandas module not found")

try:
    import numpy
    print("✅ numpy module imported successfully")
except ImportError:
    print("❌ numpy module not found")

try:
    import psycopg2
    print("✅ psycopg2 module imported successfully")
except ImportError:
    print("❌ psycopg2 module not found")

try:
    from sqlalchemy import create_engine
    print("✅ SQLAlchemy module imported successfully")
except ImportError:
    print("❌ SQLAlchemy module not found")

print("Test completed successfully!")
