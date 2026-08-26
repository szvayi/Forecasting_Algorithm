"""
测试配置文件
pytest配置和fixture定义
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


@pytest.fixture
def sample_forecast_data():
    """生成示例预测数据"""
    dates = pd.date_range('2026-02-01', periods=150, freq='D')
    data = []
    
    for i, date in enumerate(dates):
        if i % 7 == 0:  # 每周一条记录
            spu = f'SKU{str(i % 10 + 1).zfill(3)}'
            wmape = np.random.uniform(0.05, 0.50)
            data.append({
                'spu': spu,
                'run_date': date,
                'forecast_target_date': date + timedelta(days=7),
                'winner_algo': np.random.choice(['Prophet', 'XGBoost', 'LightGBM']),
                'validation_wmape': wmape,
                'sku_accuracy_json': '{}',
                'sku_share_json': '{}',
                'best_params': '{}',
                'training_weeks': 52,
                'data_end_date': date
            })
    
    return pd.DataFrame(data)


@pytest.fixture
def sample_anomalies():
    """生成示例异常数据"""
    return [
        {
            'type': 'WMAPE_THRESHOLD_EXCEEDED',
            'spu': 'SKU001',
            'run_date': datetime(2026, 3, 1),
            'value': 0.45,
            'threshold': 0.30,
            'message': 'SPU SKU001 WMAPE 45.00% exceeds threshold 30.00%'
        },
        {
            'type': 'WMAPE_HIGH',
            'spu': 'SKU002',
            'run_date': datetime(2026, 3, 1),
            'value': 0.38,
            'mean': 0.15,
            'std': 0.08,
            'upper_bound': 0.39,
            'message': 'SPU SKU002 WMAPE 38.00% is significantly higher than average 15.00%'
        }
    ]


@pytest.fixture
def sample_alerts():
    """生成示例告警数据"""
    return [
        {
            'alert_id': 'ALERT_WMAPE_THRESHOLD_EXCEEDED_SKU001_2026-03-01',
            'alert_type': 'WMAPE_THRESHOLD_EXCEEDED',
            'spu': 'SKU001',
            'run_date': datetime(2026, 3, 1),
            'severity': 'HIGH',
            'message': 'SPU SKU001 WMAPE 45.00% exceeds threshold 30.00%',
            'created_at': datetime.now()
        },
        {
            'alert_id': 'ALERT_WMAPE_HIGH_SKU002_2026-03-01',
            'alert_type': 'WMAPE_HIGH',
            'spu': 'SKU002',
            'run_date': datetime(2026, 3, 1),
            'severity': 'MEDIUM',
            'message': 'SPU SKU002 WMAPE 38.00% is significantly higher than average 15.00%',
            'created_at': datetime.now()
        }
    ]


@pytest.fixture
def sample_spu_data():
    """生成示例SPU数据"""
    dates = pd.date_range('2025-01-01', periods=100, freq='W')
    data = {
        'date': dates,
        'spu': ['SPU001'] * 100,
        'sales': np.random.randint(100, 1000, 100),
        'sku': ['SKU001', 'SKU002', 'SKU003'] * 33 + ['SKU001']
    }
    return pd.DataFrame(data)


@pytest.fixture
def sample_spu_idx_data():
    """生成示例SPU-SKU索引数据"""
    dates = pd.date_range('2025-01-01', periods=100, freq='W')
    data = {
        'date': dates * 3,
        'spu': ['SPU001'] * 300,
        'sku': ['SKU001', 'SKU002', 'SKU003'] * 100,
        'sales': np.random.randint(10, 100, 300)
    }
    return pd.DataFrame(data)


@pytest.fixture
def sample_series():
    """生成示例时间序列数据"""
    dates = pd.date_range('2025-01-01', periods=100, freq='W')
    sales = np.random.randint(100, 1000, 100)
    return pd.Series(sales, index=dates)
