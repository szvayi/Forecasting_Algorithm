"""
核心函数单元测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from types import SimpleNamespace


class TestCoreFunctions:
    """核心函数测试类"""
    
    def test_calculate_wmape_basic(self):
        """测试基本WMAPE计算"""
        from src.forecasting.predictors import calculate_wmape
        
        # 准备测试数据
        actual = pd.Series([100, 200, 300, 400, 500])
        pred = pd.Series([110, 190, 310, 390, 510])
        
        # 计算WMAPE
        wmape = calculate_wmape(actual, pred)
        
        # 验证结果
        assert isinstance(wmape, float)
        assert wmape >= 0
        assert wmape < 1
    
    def test_calculate_wmape_edge_cases(self):
        """测试WMAPE边界情况"""
        from src.forecasting.predictors import calculate_wmape
        
        # 全部为零
        actual = pd.Series([0, 0, 0])
        pred = pd.Series([0, 0, 0])
        wmape = calculate_wmape(actual, pred)
        assert wmape == 0
        
        # 完全预测准确
        actual = pd.Series([100, 200, 300])
        pred = pd.Series([100, 200, 300])
        wmape = calculate_wmape(actual, pred)
        assert wmape == 0
        
        # 完全预测错误
        actual = pd.Series([100, 200, 300])
        pred = pd.Series([0, 0, 0])
        wmape = calculate_wmape(actual, pred)
        assert wmape == 1
    
    def test_clean_series_basic(self):
        """测试基本数据清洗"""
        from src.forecasting.predictors import clean_series
        
        # 准备测试数据
        series = pd.Series([100, 200, np.nan, 400, 500])
        
        # 清洗数据
        cleaned = clean_series(series)
        
        # 验证结果
        assert not cleaned.isna().any()
        assert len(cleaned) >= len(series) - 1
    
    def test_clean_series_edge_cases(self):
        """测试数据清洗边界情况"""
        from src.forecasting.predictors import clean_series
        
        # 全部为NaN
        series = pd.Series([np.nan, np.nan, np.nan])
        cleaned = clean_series(series)
        assert len(cleaned) == 0
        
        # 无NaN
        series = pd.Series([100, 200, 300])
        cleaned = clean_series(series)
        assert len(cleaned) == 3
        assert (cleaned == series).all()
    
    def test_get_current_week_end(self):
        """测试获取当前周结束日期"""
        from src.forecasting.predictors import get_current_week_end
        
        # 获取当前周结束日期
        week_end = get_current_week_end()
        
        # 验证结果
        assert isinstance(week_end, pd.Timestamp)
        assert week_end.dayofweek == 6  # 周日
    
    def test_run_all_models_basic(self):
        """测试模型运行"""
        from src.forecasting.predictors import run_all_models
        
        # 准备测试数据
        train = pd.Series(np.random.randint(100, 1000, 50), 
                         index=pd.date_range('2025-01-01', periods=50, freq='W'))
        test = pd.Series(np.random.randint(100, 1000, 10), 
                        index=pd.date_range('2026-01-01', periods=10, freq='W'))
        
        # 运行模型
        results, base_results = run_all_models(train, test, mode='smart', verbose=False)
        
        # 验证结果
        assert isinstance(results, list)
        assert len(results) > 0
        assert isinstance(base_results, dict)
        
        # 验证每个结果
        for result in results:
            assert 'name' in result
            assert 'wmape' in result
            assert 'preds' in result
    
    def test_process_single_spu_basic(self):
        """测试单个SPU处理"""
        from src.forecasting import predictors

        fake_profile = object()
        fake_kernel = SimpleNamespace()

        def fake_process_single_spu(*args, **kwargs):
            return pd.DataFrame({"winner_algo": ["FakeModel"]}), "ignored", None, fake_profile

        fake_kernel.process_single_spu = fake_process_single_spu
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(predictors, "forecast_kernel", fake_kernel, raising=False)
        try:
            df_all = pd.DataFrame(
                {
                    "date": pd.date_range("2025-01-01", periods=20, freq="W"),
                    "spu": ["SPU001"] * 20,
                    "sales": np.random.randint(100, 1000, 20),
                    "sku": ["SKU001"] * 20,
                }
            )

            result, error, profile = predictors.process_single_spu("SPU001", df_all, verbose=False)

            assert result is not None
            assert error is None
            assert profile is fake_profile
        finally:
            monkeypatch.undo()

    def test_process_single_spu_uses_kernel_alias(self, monkeypatch):
        """测试预测器层只通过 kernel 走单个 SPU 处理"""
        from src.forecasting import predictors

        fake_profile = object()
        fake_kernel = SimpleNamespace()

        def fake_process_single_spu(*args, **kwargs):
            return pd.DataFrame({"winner_algo": ["FakeModel"]}), "ignored", None, fake_profile

        fake_kernel.process_single_spu = fake_process_single_spu
        monkeypatch.setattr(predictors, "forecast_kernel", fake_kernel, raising=False)

        df_all = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=20, freq="W"),
                "spu": ["SPU001"] * 20,
                "sales": np.arange(1, 21),
                "sku": ["SKU001"] * 20,
            }
        )

        result, error, profile = predictors.process_single_spu("SPU001", df_all, verbose=False)

        assert result is not None
        assert error is None
        assert profile is fake_profile

    def test_calculate_dynamic_shares_basic(self):
        """测试动态份额计算"""
        from src.forecasting.predictors import calculate_dynamic_shares
        
        # 准备测试数据
        dates = pd.date_range('2025-01-01', periods=100, freq='W')
        data = {
            'date': np.tile(dates, 3),
            'spu': ['SPU001'] * 300,
            'sku': ['SKU001', 'SKU002', 'SKU003'] * 100,
            'sales': np.random.randint(10, 100, 300)
        }
        df_spu_idx = pd.DataFrame(data).set_index('date')
        spu = 'SPU001'
        spu_sales = pd.Series(np.random.randint(100, 1000, 100), 
                             index=pd.date_range('2025-01-01', periods=100, freq='W'))
        future_dates = pd.date_range('2026-01-01', periods=10, freq='W')
        
        # 计算动态份额
        json_list, share_df = calculate_dynamic_shares(df_spu_idx, spu, spu_sales, future_dates)
        
        # 验证结果
        assert isinstance(json_list, np.ndarray)
        assert isinstance(share_df, pd.DataFrame)
        assert len(json_list) == len(future_dates)
        assert len(share_df) == len(future_dates)
        assert len(share_df.columns) == 3  # SKU001, SKU002, SKU003
    
    def test_calculate_spu_accuracy_basic(self):
        """测试SPU准确性计算"""
        from src.forecasting.predictors import calculate_spu_accuracy
        
        # 准备测试数据
        actual = pd.Series([100, 200, 300, 400, 500])
        pred = pd.Series([110, 190, 310, 390, 510])
        
        # 计算准确性
        accuracy = calculate_spu_accuracy(actual, pred)
        
        # 验证结果
        assert isinstance(accuracy, dict)
        assert 'wmape' in accuracy
        assert 'mape' in accuracy
        assert 'mae' in accuracy
        assert 'rmse' in accuracy
    
    def test_calculate_sku_accuracy_basic(self):
        """测试SKU准确性计算"""
        from src.forecasting.predictors import calculate_sku_accuracy
        
        # 准备测试数据
        actual = pd.DataFrame({
            'SKU001': [10, 20, 30],
            'SKU002': [40, 50, 60],
            'SKU003': [70, 80, 90]
        })
        pred = pd.DataFrame({
            'SKU001': [11, 19, 31],
            'SKU002': [39, 51, 59],
            'SKU003': [69, 81, 89]
        })
        
        # 计算准确性
        accuracy = calculate_sku_accuracy(actual, pred)
        
        # 验证结果
        assert isinstance(accuracy, dict)
        assert 'wmape' in accuracy
        assert 'sku_metrics' in accuracy

    def test_blend_with_prior_weights_keeps_simplex_and_inertia(self):
        from src.forecasting.predictors import _blend_with_prior_weights

        prior = np.array([0.7, 0.2, 0.1], dtype=float)
        optimized = np.array([0.1, 0.8, 0.1], dtype=float)
        blended = _blend_with_prior_weights(prior, optimized, regime="sparse")

        assert np.isclose(blended.sum(), 1.0)
        assert np.all(blended >= 0)
        # Sparse regime should keep stronger inertia to prior than raw optimized.
        assert blended[0] > optimized[0]
