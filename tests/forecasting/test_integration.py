"""
集成测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock


class TestIntegration:
    """集成测试类"""
    
    @pytest.fixture
    def sample_data(self):
        """生成示例数据"""
        dates = pd.date_range('2025-01-01', periods=100, freq='W')
        
        # SPU数据
        spu_data = {
            'date': dates,
            'spu': ['SPU001'] * 100,
            'sales': np.random.randint(100, 1000, 100),
            'price': np.random.uniform(10, 50, 100),
            'ad_cost': np.random.uniform(100, 500, 100)
        }
        df_spu = pd.DataFrame(spu_data)
        
        # SKU数据
        dates_all = np.tile(dates, 3)
        sku_data = {
            'date': dates_all,
            'spu': ['SPU001'] * 300,
            'sku': ['SKU001', 'SKU002', 'SKU003'] * 100,
            'sales': np.random.randint(10, 100, 300),
            'price': np.random.uniform(10, 50, 300)
        }
        df_sku = pd.DataFrame(sku_data)
        
        # 合并数据
        df_all = pd.concat([df_spu, df_sku], ignore_index=True)
        
        return df_all

    @pytest.fixture
    def monitor_data(self):
        dates = pd.date_range('2026-02-01', periods=12, freq='W')
        return pd.DataFrame({
            'spu': ['SPU001'] * len(dates),
            'run_date': dates,
            'forecast_target_date': dates + pd.Timedelta(days=7),
            'winner_algo': ['Prophet'] * len(dates),
            'validation_wmape': np.linspace(0.1, 0.35, len(dates)),
            'sku_accuracy_json': ['{}'] * len(dates),
            'sku_share_json': ['{}'] * len(dates),
            'best_params': ['{}'] * len(dates),
            'training_weeks': [52] * len(dates),
            'data_end_date': dates,
        })
    
    @patch('src.forecasting.main.predict_future')
    @patch('src.forecasting.main.calculate_dynamic_shares')
    @patch('src.forecasting.main.run_all_models')
    def test_spu_prediction_pipeline(self, mock_run_models, mock_dynamic_shares, mock_predict_future, sample_data):
        """测试SPU预测流程"""
        from src.forecasting.main import process_single_spu
        
        # 模拟模型运行结果
        mock_run_models.return_value = (
            [{
                'name': 'Prophet',
                'wmape': 0.15,
                'preds': np.random.randint(100, 1000, 10),
                'params': {'param1': 'value1'},
                'model': MagicMock(),
            }],
            {'Prophet': {'name': 'Prophet'}},
        )
        mock_predict_future.return_value = np.random.randint(100, 1000, 16)
        
        # 模拟动态份额计算
        mock_dynamic_shares.return_value = (
            ['{"SKU001":0.3,"SKU002":0.4,"SKU003":0.3}'] * 16,
            pd.DataFrame({
                'SKU001': [0.3] * 16,
                'SKU002': [0.4] * 16,
                'SKU003': [0.3] * 16
            }, index=pd.date_range('2026-01-05', periods=16, freq='W'))
        )
        
        # 运行预测
        result, message, _viz, profile = process_single_spu('SPU001', sample_data, verbose=False)
        
        # 验证结果
        assert result is not None
        assert "Prophet" in message
        assert 'winner_algo' in result.columns
        assert profile is None
    
    @patch('src.forecasting.monitor.create_engine')
    def test_monitoring_pipeline(self, mock_create_engine, monitor_data):
        """测试监控流程"""
        from src.forecasting.monitor import ForecastingMonitor
        
        # 模拟数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine
        
        # 模拟查询结果
        mock_conn.execute.return_value = monitor_data
        
        # 创建监控器
        monitor = ForecastingMonitor('postgresql://test:test@localhost:5432/test_db', wmape_threshold=0.30)
        
        # 运行监控
        result = monitor.run_monitoring(days=30)
        
        # 验证结果
        assert 'summary' in result
        assert 'stats' in result
        assert 'anomalies' in result
        assert 'trends' in result
        assert 'alerts' in result
        
        # 验证摘要
        summary = result['summary']
        assert summary['total_records'] > 0
        assert summary['threshold_exceeded_count'] >= 0
        assert summary['anomaly_count'] >= 0
        assert summary['alert_count'] >= 0
    
    @patch('src.forecasting.main.predict_future')
    @patch('src.forecasting.main.calculate_dynamic_shares')
    @patch('src.forecasting.main.run_all_models')
    @patch('src.forecasting.monitor.create_engine')
    def test_end_to_end_workflow(self, mock_create_engine, mock_run_all_models, mock_dynamic_shares, mock_predict_future, sample_data, monitor_data):
        """测试端到端工作流"""
        from src.forecasting.main import process_single_spu
        from src.forecasting.monitor import ForecastingMonitor
        
        mock_run_all_models.return_value = (
            [{
                'name': 'Prophet',
                'wmape': 0.15,
                'preds': np.random.randint(100, 1000, 10),
                'params': {'param1': 'value1'},
                'model': MagicMock(),
            }],
            {'Prophet': {'name': 'Prophet'}},
        )
        mock_predict_future.return_value = np.random.randint(100, 1000, 16)
        mock_dynamic_shares.return_value = (
            ['{"SKU001":0.3,"SKU002":0.4,"SKU003":0.3}'] * 16,
            pd.DataFrame({
                'SKU001': [0.3] * 16,
                'SKU002': [0.4] * 16,
                'SKU003': [0.3] * 16
            }, index=pd.date_range('2026-01-01', periods=16, freq='W'))
        )
        
        # 模拟数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine
        
        # 模拟查询结果
        mock_conn.execute.return_value = monitor_data
        
        # 步骤1: 运行预测
        forecast_result, message, _viz, _profile = process_single_spu('SPU001', sample_data, verbose=False)
        assert forecast_result is not None
        
        # 步骤2: 运行监控
        monitor = ForecastingMonitor('postgresql://test:test@localhost:5432/test_db', wmape_threshold=0.30)
        monitor_result = monitor.run_monitoring(days=30)
        assert monitor_result is not None
        
        # 步骤3: 验证结果
        assert "Prophet" in message
        assert 'winner_algo' in forecast_result.columns
        assert monitor_result['summary']['total_records'] > 0
