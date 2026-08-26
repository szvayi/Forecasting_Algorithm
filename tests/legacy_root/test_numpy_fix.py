import numpy as np
import pandas as pd
from algorithm_engine import run_all_models

print(f'NumPy version: {np.__version__}')
print(f'NumPy float_ available: {hasattr(np, "float_")}')
print(f'NumPy float64 available: {hasattr(np, "float64")}')

# Test the algorithm engine
train = pd.Series(np.random.rand(100)*100, index=pd.date_range('2020-01-01', periods=100, freq='W'))
test = pd.Series(np.random.rand(16)*100, index=pd.date_range('2022-01-01', periods=16, freq='W'))

print('\nStarting algorithm test...')
results, base = run_all_models(train, test, mode='fast')
print(f'Total models: {len(results)}, Base models: {len(base)}')
print('Test completed successfully!')