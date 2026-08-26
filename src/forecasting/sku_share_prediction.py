"""
SKU份额预测模型模块
用于实现SKU份额预测功能
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor


class SKUSharePredictor:
    """SKU份额预测器"""
    
    def __init__(self, method: str = 'dynamic_regression'):
        """
        初始化SKU份额预测器
        
        Args:
            method: 预测方法
                - 'dynamic_regression': 动态回归
                - 'random_forest': 随机森林
                - 'xgboost': XGBoost
                - 'lightgbm': LightGBM
                - 'simple_ewma': 简单指数移动平均
        """
        self.method = method
        self.models = {}
        self.feature_names = []
        
        self.logger = logging.getLogger('forecasting')
        self.logger.info(f"SKUSharePredictor initialized with method: {method}")
    
    def fit(self, sku_sales_history: pd.DataFrame):
        """
        训练份额预测模型
        
        Args:
            sku_sales_history: SKU历史销量DataFrame
                列: [date, sku, sales]
        """
        try:
            # 按日期和SKU汇总销量
            sku_sales = sku_sales_history.groupby(['date', 'sku'])['sales'].sum().unstack(fill_value=0)
            sku_sales = sku_sales.sort_index()
            
            # 计算每日总销量
            total_sales = sku_sales.sum(axis=1)
            
            # 计算每日份额
            daily_shares = sku_sales.div(total_sales, axis=0).fillna(0)
            
            # 根据方法训练模型
            if self.method == 'dynamic_regression':
                self._fit_dynamic_regression(daily_shares)
            elif self.method == 'random_forest':
                self._fit_random_forest(daily_shares)
            elif self.method == 'xgboost':
                self._fit_xgboost(daily_shares)
            elif self.method == 'lightgbm':
                self._fit_lightgbm(daily_shares)
            elif self.method == 'simple_ewma':
                self._fit_simple_ewma(daily_shares)
            else:
                self._fit_simple_ewma(daily_shares)
            
            self.logger.info(f"SKU份额预测模型训练完成, SKU数量: {len(sku_sales.columns)}")
            
        except Exception as e:
            self.logger.error(f"SKU份额预测模型训练失败: {e}")
            raise
    
    def _fit_dynamic_regression(self, daily_shares: pd.DataFrame):
        """动态回归方法"""
        self.models = {}
        
        for sku in daily_shares.columns:
            series = daily_shares[sku]
            
            # 创建滞后特征
            lag_features = pd.DataFrame()
            for lag in [1, 2, 3, 4]:
                lag_features[f'lag_{lag}'] = series.shift(lag)
            
            # 创建移动平均特征
            for window in [4, 8]:
                lag_features[f'ma_{window}'] = series.shift(1).rolling(window).mean()
            
            # 删除缺失值
            features = lag_features.dropna()
            target = series[lag_features.index[0]:]
            
            if len(features) >= 10:
                # 训练 Ridge 回归模型
                model = Ridge(alpha=1.0)
                model.fit(features, target)
                
                self.models[sku] = {
                    'model': model,
                    'features': features.columns.tolist(),
                    'last_values': series[-4:].tolist() if len(series) >= 4 else [series.mean()] * 4
                }
            
            self.feature_names = features.columns.tolist() if len(features) > 0 else []
    
    def _fit_random_forest(self, daily_shares: pd.DataFrame):
        """随机森林方法"""
        self.models = {}
        
        for sku in daily_shares.columns:
            series = daily_shares[sku]
            
            # 创建滞后特征
            lag_features = pd.DataFrame()
            for lag in [1, 2, 3, 4]:
                lag_features[f'lag_{lag}'] = series.shift(lag)
            
            # 删除缺失值
            features = lag_features.dropna()
            target = series[lag_features.index[0]:]
            
            if len(features) >= 10:
                # 训练随机森林模型
                model = RandomForestRegressor(n_estimators=100, max_depth=5, random_state=42)
                model.fit(features, target)
                
                self.models[sku] = {
                    'model': model,
                    'features': features.columns.tolist(),
                    'last_values': series[-4:].tolist() if len(series) >= 4 else [series.mean()] * 4
                }
            
            self.feature_names = features.columns.tolist() if len(features) > 0 else []
    
    def _fit_xgboost(self, daily_shares: pd.DataFrame):
        """XGBoost方法"""
        self.models = {}
        
        for sku in daily_shares.columns:
            series = daily_shares[sku]
            
            # 创建滞后特征
            lag_features = pd.DataFrame()
            for lag in [1, 2, 3, 4]:
                lag_features[f'lag_{lag}'] = series.shift(lag)
            
            # 删除缺失值
            features = lag_features.dropna()
            target = series[lag_features.index[0]:]
            
            if len(features) >= 10:
                # 训练XGBoost模型
                model = XGBRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)
                model.fit(features, target)
                
                self.models[sku] = {
                    'model': model,
                    'features': features.columns.tolist(),
                    'last_values': series[-4:].tolist() if len(series) >= 4 else [series.mean()] * 4
                }
            
            self.feature_names = features.columns.tolist() if len(features) > 0 else []
    
    def _fit_lightgbm(self, daily_shares: pd.DataFrame):
        """LightGBM方法"""
        self.models = {}
        
        for sku in daily_shares.columns:
            series = daily_shares[sku]
            
            # 创建滞后特征
            lag_features = pd.DataFrame()
            for lag in [1, 2, 3, 4]:
                lag_features[f'lag_{lag}'] = series.shift(lag)
            
            # 删除缺失值
            features = lag_features.dropna()
            target = series[lag_features.index[0]:]
            
            if len(features) >= 10:
                # 训练LightGBM模型
                model = LGBMRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)
                model.fit(features, target)
                
                self.models[sku] = {
                    'model': model,
                    'features': features.columns.tolist(),
                    'last_values': series[-4:].tolist() if len(series) >= 4 else [series.mean()] * 4
                }
            
            self.feature_names = features.columns.tolist() if len(features) > 0 else []
    
    def _fit_simple_ewma(self, daily_shares: pd.DataFrame):
        """简单指数移动平均方法"""
        self.models = {}
        
        for sku in daily_shares.columns:
            series = daily_shares[sku]
            
            # 计算指数移动平均
            ewma_span = 8
            ewma = series.ewm(span=ewma_span, adjust=False).mean()
            
            self.models[sku] = {
                'method': 'ewma',
                'span': ewma_span,
                'last_ewma': ewma.iloc[-1] if len(ewma) > 0 else series.mean(),
                'last_values': series[-4:].tolist() if len(series) >= 4 else [series.mean()] * 4
            }
    
    def predict(self, n_steps: int = 4) -> pd.DataFrame:
        """
        预测未来份额
        
        Args:
            n_steps: 预测步数
            
        Returns:
            pd.DataFrame: 预测的份额DataFrame
        """
        predictions = {}
        
        for sku, model_info in self.models.items():
            if model_info['method'] == 'ewma':
                # 简单指数移动平均
                last_ewma = model_info['last_ewma']
                predictions[sku] = [last_ewma] * n_steps
            else:
                # 使用训练的模型预测
                model = model_info['model']
                features = model_info['features']
                last_values = model_info['last_values']
                
                # 生成预测序列
                pred_series = []
                for step in range(n_steps):
                    # 创建特征
                    feature_dict = {}
                    for i, feature in enumerate(features):
                        if 'lag' in feature:
                            lag = int(feature.split('_')[1])
                            if step >= lag:
                                feature_dict[feature] = pred_series[-lag]
                            else:
                                feature_dict[feature] = last_values[-lag] if len(last_values) >= lag else 0
                        elif 'ma' in feature:
                            window = int(feature.split('_')[1])
                            if len(pred_series) >= window:
                                feature_dict[feature] = np.mean(pred_series[-window:])
                            else:
                                feature_dict[feature] = np.mean(last_values[-window:]) if len(last_values) >= window else 0
                    
                    # 预测
                    feature_df = pd.DataFrame([feature_dict])
                    pred = model.predict(feature_df)[0]
                    pred = max(0.001, min(1.0, pred))  # 限制在0-1之间
                    pred_series.append(pred)
                
                predictions[sku] = pred_series
        
        # 创建预测DataFrame
        future_dates = pd.date_range(datetime.now().date(), periods=n_steps + 1, freq='W')[1:]
        pred_df = pd.DataFrame(predictions, index=future_dates)
        
        # 归一化确保份额总和为1
        pred_df = pred_df.div(pred_df.sum(axis=1), axis=0).fillna(0)
        
        self.logger.info(f"SKU份额预测完成, 预测步数: {n_steps}")
        
        return pred_df
    
    def predict_with_spu_forecast(self, spu_forecast: pd.Series, n_steps: int = 4) -> pd.DataFrame:
        """
        结合SPU预测的SKU份额预测
        
        Args:
            spu_forecast: SPU预测销量
            n_steps: 预测步数
            
        Returns:
            pd.DataFrame: SKU预测销量DataFrame
        """
        # 预测份额
        share_df = self.predict(n_steps)
        
        # 计算SKU预测销量
        sku_forecast = share_df.multiply(spu_forecast.values, axis=0)
        
        self.logger.info(f"结合SPU预测的SKU份额预测完成")
        
        return sku_forecast
    
    def adjust_shares(self, base_shares: pd.DataFrame, adjustments: Dict[str, Dict[str, float]]) -> pd.DataFrame:
        """
        调整份额
        
        Args:
            base_shares: 基础份额DataFrame
            adjustments: 调整字典 {sku: {date: adjustment_factor}}
            
        Returns:
            pd.DataFrame: 调整后的份额DataFrame
        """
        adjusted_shares = base_shares.copy()
        
        for sku, sku_adjustments in adjustments.items():
            if sku in adjusted_shares.columns:
                for date, factor in sku_adjustments.items():
                    if date in adjusted_shares.index:
                        adjusted_shares.loc[date, sku] *= factor
        
        # 归一化
        adjusted_shares = adjusted_shares.div(adjusted_shares.sum(axis=1), axis=0).fillna(0)
        
        self.logger.info(f"SKU份额调整完成")
        
        return adjusted_shares
    
    def validate_shares(self, actual_shares: pd.DataFrame, predicted_shares: pd.DataFrame) -> Dict[str, Any]:
        """
        验证份额预测准确性
        
        Args:
            actual_shares: 实际份额DataFrame
            predicted_shares: 预测份额DataFrame
            
        Returns:
            Dict: 验证结果
        """
        results = {
            'wmape': {},
            'mape': {},
            'rmse': {}
        }
        
        for sku in actual_shares.columns:
            if sku in predicted_shares.columns:
                actual = actual_shares[sku].values
                pred = predicted_shares[sku].values
                
                # 计算WMAPE
                mask = actual > 0
                if mask.any():
                    wmape = np.sum(np.abs(actual[mask] - pred[mask])) / np.sum(actual[mask])
                    results['wmape'][sku] = wmape
                    
                    # 计算MAPE
                    mape = np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask]))
                    results['mape'][sku] = mape
                    
                    # 计算RMSE
                    rmse = np.sqrt(np.mean((actual - pred) ** 2))
                    results['rmse'][sku] = rmse
        
        # 计算总体指标
        if results['wmape']:
            results['overall_wmape'] = np.mean(list(results['wmape'].values()))
            results['overall_mape'] = np.mean(list(results['mape'].values()))
            results['overall_rmse'] = np.mean(list(results['rmse'].values()))
        
        self.logger.info(f"SKU份额验证完成, WMAPE: {results.get('overall_wmape', 0):.2%}")
        
        return results


def main():
    """主函数"""
    # 生成示例数据
    dates = pd.date_range('2026-01-01', periods=50, freq='W')
    
    # SKU历史销量
    sku_sales_history = []
    for date in dates:
        for sku in ['SKU001', 'SKU002', 'SKU003', 'SKU004', 'SKU005']:
            sales = np.random.randint(10, 100)
            sku_sales_history.append({
                'date': date,
                'sku': sku,
                'sales': sales
            })
    
    sku_sales_history = pd.DataFrame(sku_sales_history)
    
    # 训练份额预测模型
    predictor = SKUSharePredictor(method='dynamic_regression')
    predictor.fit(sku_sales_history)
    
    # 预测未来份额
    future_shares = predictor.predict(n_steps=4)
    print(f"\n未来份额预测:\n{future_shares}")
    
    # 生成SPU预测
    spu_forecast = pd.Series([500, 520, 540, 560], index=future_shares.index)
    
    # 结合SPU预测的SKU预测
    sku_forecast = predictor.predict_with_spu_forecast(spu_forecast, n_steps=4)
    print(f"\nSKU预测销量:\n{sku_forecast}")
    
    return predictor


if __name__ == '__main__':
    main()
