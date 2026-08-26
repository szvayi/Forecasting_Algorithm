"""
监控模块单元测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock


class TestForecastingMonitor:
    """监控模块测试类"""
    
    @pytest.fixture
    def sample_data(self):
        """生成示例数据"""
        dates = pd.date_range('2026-02-01', periods=50, freq='W')
        data = []
        
        for i, date in enumerate(dates):
            spu = f'SKU{str(i % 5 + 1).zfill(3)}'
            wmape = np.random.uniform(0.05, 0.45)
            data.append({
                'spu': spu,
                'run_date': date,
                'forecast_target_date': date + pd.Timedelta(days=7),
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
    def monitor(self):
        """创建监控器实例"""
        from src.forecasting.monitor import ForecastingMonitor
        return ForecastingMonitor('postgresql://test:test@localhost:5432/test_db', wmape_threshold=0.30)
    
    def test_calculate_wmape_statistics_basic(self, sample_data, monitor):
        """测试基本WMAPE统计计算"""
        stats = monitor.calculate_wmape_statistics(sample_data)
        
        # 验证返回结构
        assert 'overall' in stats
        assert 'by_spu' in stats
        assert 'by_date' in stats
        assert 'by_model' in stats
        
        # 验证总体统计
        overall = stats['overall']
        assert 'mean' in overall
        assert 'median' in overall
        assert 'std' in overall
        assert 'min' in overall
        assert 'max' in overall
        assert 'threshold_exceeded_count' in overall
        assert 'threshold_exceeded_rate' in overall
        
        # 验证计算正确性
        assert overall['mean'] == sample_data['validation_wmape'].mean()
        assert overall['median'] == sample_data['validation_wmape'].median()
        assert overall['std'] == sample_data['validation_wmape'].std()
        assert overall['min'] == sample_data['validation_wmape'].min()
        assert overall['max'] == sample_data['validation_wmape'].max()
    
    def test_calculate_wmape_statistics_threshold(self, sample_data, monitor):
        """测试超阈值统计计算"""
        stats = monitor.calculate_wmape_statistics(sample_data)
        
        # 验证超阈值统计
        threshold_exceeded = (sample_data['validation_wmape'] > 0.30).sum()
        assert stats['overall']['threshold_exceeded_count'] == threshold_exceeded
        
        threshold_exceeded_rate = (sample_data['validation_wmape'] > 0.30).mean()
        assert abs(stats['overall']['threshold_exceeded_rate'] - threshold_exceeded_rate) < 0.001
    
    def test_calculate_wmape_statistics_grouping(self, sample_data, monitor):
        """测试分组统计计算"""
        stats = monitor.calculate_wmape_statistics(sample_data)
        
        # 验证SPU分组统计
        for spu in sample_data['spu'].unique():
            spu_data = sample_data[sample_data['spu'] == spu]
            assert spu in stats['by_spu']
            assert stats['by_spu'][spu]['count'] == len(spu_data)
            assert stats['by_spu'][spu]['mean_wmape'] == spu_data['validation_wmape'].mean()
        
        # 验证日期分组统计
        for date in sample_data['run_date'].unique():
            date_data = sample_data[sample_data['run_date'] == date]
            date_str = str(date.date())
            assert date_str in stats['by_date']
            assert stats['by_date'][date_str]['count'] == len(date_data)
        
        # 验证模型分组统计
        for model in sample_data['winner_algo'].unique():
            model_data = sample_data[sample_data['winner_algo'] == model]
            assert model in stats['by_model']
            assert stats['by_model'][model]['count'] == len(model_data)
    
    def test_detect_anomalies_threshold(self, sample_data, monitor):
        """测试WMAPE超阈值检测"""
        # 确保有超阈值的数据
        sample_data.loc[0, 'validation_wmape'] = 0.45
        
        anomalies = monitor.detect_anomalies(sample_data)
        
        # 验证结果
        assert len(anomalies) > 0
        
        # 验证超阈值异常
        threshold_anomalies = [a for a in anomalies if a['type'] == 'WMAPE_THRESHOLD_EXCEEDED']
        assert len(threshold_anomalies) > 0
        
        # 验证异常详情
        for anomaly in threshold_anomalies:
            assert 'type' in anomaly
            assert 'spu' in anomaly
            assert 'run_date' in anomaly
            assert 'value' in anomaly
            assert 'threshold' in anomaly
            assert 'message' in anomaly
            assert anomaly['value'] > 0.30
    
    def test_detect_anomalies_high(self, sample_data, monitor):
        """测试WMAPE异常高检测"""
        # 确保有异常高的数据
        sample_data.loc[0, 'validation_wmape'] = 0.38
        sample_data.loc[1, 'validation_wmape'] = 0.35
        
        anomalies = monitor.detect_anomalies(sample_data)
        
        # 验证结果
        high_anomalies = [a for a in anomalies if a['type'] == 'WMAPE_HIGH']
        
        # 验证异常详情
        for anomaly in high_anomalies:
            assert 'type' in anomaly
            assert 'spu' in anomaly
            assert 'run_date' in anomaly
            assert 'value' in anomaly
            assert 'mean' in anomaly
            assert 'std' in anomaly
            assert 'upper_bound' in anomaly
            assert 'message' in anomaly
    
    def test_detect_anomalies_no_duplicate(self, sample_data, monitor):
        """测试无重复检测"""
        # 确保有超阈值的数据
        sample_data.loc[0, 'validation_wmape'] = 0.45
        
        anomalies = monitor.detect_anomalies(sample_data)
        
        # 验证无重复
        for anomaly in anomalies:
            if anomaly['type'] == 'WMAPE_THRESHOLD_EXCEEDED':
                # 超阈值的不应同时是异常高
                high_anomalies = [a for a in anomalies if a['type'] == 'WMAPE_HIGH']
                for high in high_anomalies:
                    assert not (high['spu'] == anomaly['spu'] and high['run_date'] == anomaly['run_date'])
    
    def test_analyze_trends_wmape(self, sample_data, monitor):
        """测试WMAPE趋势分析"""
        trends = monitor.analyze_trends(sample_data)
        
        # 验证结果
        assert 'wmape_trend' in trends
        assert 'model_performance_trend' in trends
        
        # 验证WMAPE趋势
        wmape_trend = trends['wmape_trend']
        if len(wmape_trend) > 0:
            assert 'recent_ma' in wmape_trend
            assert 'previous_ma' in wmape_trend
            assert 'trend' in wmape_trend
            assert 'change_pct' in wmape_trend
            assert wmape_trend['trend'] in ['increasing', 'decreasing']
    
    def test_analyze_trends_model(self, sample_data, monitor):
        """测试模型性能趋势分析"""
        trends = monitor.analyze_trends(sample_data)
        
        # 验证模型性能趋势
        model_trends = trends['model_performance_trend']
        
        for model in sample_data['winner_algo'].unique():
            if model in model_trends:
                trend = model_trends[model]
                assert 'recent_wmape' in trend
                assert 'previous_wmape' in trend
                assert 'change' in trend
                assert 'improving' in trend
    
    def test_generate_alerts_basic(self, sample_data, monitor):
        """测试告警生成"""
        # 生成异常
        sample_data.loc[0, 'validation_wmape'] = 0.45
        anomalies = monitor.detect_anomalies(sample_data)
        
        # 生成告警
        alerts = monitor.generate_alerts(anomalies)
        
        # 验证结果
        assert len(alerts) == len(anomalies)
        
        # 验证告警详情
        for alert in alerts:
            assert 'alert_id' in alert
            assert 'alert_type' in alert
            assert 'spu' in alert
            assert 'run_date' in alert
            assert 'severity' in alert
            assert 'message' in alert
            assert 'created_at' in alert
    
    def test_generate_alerts_severity(self, sample_data, monitor):
        """测试告警级别生成"""
        # 生成异常
        sample_data.loc[0, 'validation_wmape'] = 0.45
        anomalies = monitor.detect_anomalies(sample_data)
        
        # 生成告警
        alerts = monitor.generate_alerts(anomalies)
        
        # 验证告警级别
        for alert in alerts:
            if 'THRESHOLD' in alert['alert_type']:
                assert alert['severity'] == 'HIGH'
            else:
                assert alert['severity'] == 'MEDIUM'
    
    def test_generate_alerts_id(self, sample_data, monitor):
        """测试告警ID生成"""
        # 生成异常
        sample_data.loc[0, 'validation_wmape'] = 0.45
        anomalies = monitor.detect_anomalies(sample_data)
        
        # 生成告警
        alerts = monitor.generate_alerts(anomalies)
        
        # 验证告警ID格式
        for alert in alerts:
            expected_id = f"ALERT_{alert['alert_type']}_{alert['spu']}_{alert['run_date'].date()}"
            assert alert['alert_id'] == expected_id
    
    @patch('src.forecasting.monitor.create_engine')
    def test_save_alerts_to_db(self, mock_create_engine, sample_data, monitor):
        """测试告警保存到数据库"""
        # 生成异常和告警
        sample_data.loc[0, 'validation_wmape'] = 0.45
        anomalies = monitor.detect_anomalies(sample_data)
        alerts = monitor.generate_alerts(anomalies)
        
        # 模拟数据库连接
        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        
        # 保存告警
        saved_count = monitor.save_alerts_to_db(alerts)
        
        # 验证结果
        assert saved_count == len(alerts)
        mock_conn.execute.assert_called()
        mock_conn.commit.assert_called()
    
    @patch('src.forecasting.monitor.create_engine')
    def test_run_monitoring(self, mock_create_engine, sample_data, monitor):
        """测试完整监控流程"""
        # 模拟数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine
        
        # 模拟查询结果
        mock_conn.execute.return_value = sample_data
        
        # 运行监控
        result = monitor.run_monitoring(days=30)
        
        # 验证结果结构
        assert 'summary' in result
        assert 'stats' in result
        assert 'anomalies' in result
        assert 'trends' in result
        assert 'alerts' in result
        
        # 验证摘要
        summary = result['summary']
        assert 'total_records' in summary
        assert 'threshold_exceeded_count' in summary
        assert 'anomaly_count' in summary
        assert 'alert_count' in summary
        assert 'alerts_saved' in summary
