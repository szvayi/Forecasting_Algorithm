print("Testing basic Python functionality...")
print("Python version:")
import sys
print(sys.version)

print("\nTesting print function...")
print("Hello, world!")

print("\nTesting basic imports...")
try:
    import os
    print("os imported successfully")
except Exception as e:
    print("Error importing os:", e)

try:
    import time
    print("time imported successfully")
except Exception as e:
    print("Error importing time:", e)

print("\nBasic test completed!")
