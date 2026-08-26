import unittest
import pandas as pd
import numpy as np
import json
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_and_utils import calculate_dynamic_shares, clean_series, extract_seasonal_factors_52week

class TestConfigAndUtils(unittest.TestCase):

    def test_clean_series(self):
        # Test basic interpolation
        data = [10, 0, 30, 0, 50]
        s = pd.Series(data)
        cleaned = clean_series(s)
        expected = [10, 20, 30, 40, 50]
        pd.testing.assert_series_equal(cleaned, pd.Series(expected, dtype=float))

    def test_extract_seasonal_factors_52week_short_data(self):
        # Test with insufficient data (< 52 weeks)
        data = np.random.rand(20)
        s = pd.Series(data)
        result = extract_seasonal_factors_52week(s)
        result_dict = json.loads(result)
        self.assertEqual(len(result_dict), 52)
        self.assertEqual(result_dict['week_1'], 1.0)

    def test_calculate_dynamic_shares(self):
        # Mock data
        dates = pd.date_range(start='2023-01-01', periods=10, freq='W')
        spu = 'SPU_001'
        
        # Create a mock df_spu_idx
        # Columns: date, sku, sales
        data = []
        for d in dates:
            data.append({'date': d, 'sku': 'SKU_A', 'sales': 100})
            data.append({'date': d, 'sku': 'SKU_B', 'sales': 50})
        
        df = pd.DataFrame(data)
        # The function expects df_spu_idx to have 'sku' and 'sales' columns, and index as date?
        # Let's check the function implementation:
        # sku_sales = df_spu_idx.groupby([pd.Grouper(freq='W'), 'sku'])['sales'].sum().unstack(fill_value=0)
        # So df_spu_idx needs to be a DataFrame with DatetimeIndex or 'date' column?
        # The function uses pd.Grouper(freq='W') on the index if it's datetime, or it needs 'date' column?
        # The code: df_spu_idx.groupby([pd.Grouper(freq='W'), 'sku'])
        # This implies the index is datetime.
        
        df_spu_idx = df.set_index('date')
        
        # Mock spu_sales_weekly (aggregated)
        spu_sales_weekly = df_spu_idx.groupby(pd.Grouper(freq='W'))['sales'].sum()
        
        # Future dates
        future_dates = pd.date_range(start=dates[-1] + pd.Timedelta(weeks=1), periods=5, freq='W')
        
        json_list, future_df = calculate_dynamic_shares(df_spu_idx, spu, spu_sales_weekly, future_dates)
        
        # Assertions
        self.assertEqual(len(json_list), 5)
        self.assertEqual(len(future_df), 5)
        self.assertAlmostEqual(future_df.iloc[0].sum(), 1.0) # Shares should sum to 1
        
        # Check SKU columns
        self.assertIn('SKU_A', future_df.columns)
        self.assertIn('SKU_B', future_df.columns)
        
        # Check values (should be roughly 2/3 and 1/3)
        self.assertTrue(future_df['SKU_A'].iloc[0] > future_df['SKU_B'].iloc[0])

if __name__ == '__main__':
    unittest.main()
