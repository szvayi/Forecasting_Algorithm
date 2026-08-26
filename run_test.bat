@echo off
echo Starting prediction...
cd /d C:\Users\VY0814\Forecasting_Algorithm
C:\Users\VY0814\Forecasting_Algorithm\.venv\Scripts\python.exe -u -c "import sys; sys.path.insert(0, '.'); from src.forecasting.models import FeatureEngineer; print('FeatureEngineer imported successfully'); fe = FeatureEngineer(); print('FeatureEngineer instantiated successfully')"
echo Prediction completed.
pause