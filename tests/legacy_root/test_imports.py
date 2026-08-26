import traceback

# 测试导入各个模块
try:
    print("Testing Flask...")
    from flask import Flask
    print("Flask imported successfully")
except Exception as e:
    print("Error importing Flask:", e)
    traceback.print_exc()

try:
    print("\nTesting pandas...")
    import pandas as pd
    print("pandas imported successfully")
except Exception as e:
    print("Error importing pandas:", e)
    traceback.print_exc()

try:
    print("\nTesting numpy...")
    import numpy as np
    print("numpy imported successfully")
except Exception as e:
    print("Error importing numpy:", e)
    traceback.print_exc()

try:
    print("\nTesting tensorflow...")
    import tensorflow as tf
    print("tensorflow imported successfully")
except Exception as e:
    print("Error importing tensorflow:", e)
    traceback.print_exc()

try:
    print("\nTesting config_and_utils...")
    from config_and_utils import *
    print("config_and_utils imported successfully")
except Exception as e:
    print("Error importing config_and_utils:", e)
    traceback.print_exc()

try:
    print("\nTesting algorithm_engine...")
    from algorithm_engine import *
    print("algorithm_engine imported successfully")
except Exception as e:
    print("Error importing algorithm_engine:", e)
    traceback.print_exc()

try:
    print("\nTesting main...")
    from main import get_data_from_db, process_single_spu, save_to_database
    print("main imported successfully")
except Exception as e:
    print("Error importing main:", e)
    traceback.print_exc()

print("\nImport test completed!")
