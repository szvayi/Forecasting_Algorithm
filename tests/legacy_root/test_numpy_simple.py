print("Testing NumPy installation...")
import numpy as np
print(f"NumPy version: {np.__version__}")
print("NumPy imported successfully!")

# Test basic functionality
arr = np.array([1, 2, 3, 4, 5])
print(f"Test array: {arr}")
print(f"Mean: {arr.mean()}")

print("\nAll tests passed!")