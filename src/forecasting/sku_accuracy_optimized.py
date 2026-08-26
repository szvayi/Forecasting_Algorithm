"""
SKU准确性评估优化模块
用于优化SKU准确性评估逻辑
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime


def calculate_sku_accuracy_optimized(
    actual: pd.DataFrame, 
    pred: pd.DataFrame,
    sku_accuracy_threshold: float = 0.01
) -> Dict[str, Any]:
    """
    优化的SKU准确性评估
    
    Args:
        actual: 实际销量DataFrame
        pred: 预测销量DataFrame
        sku_accuracy_threshold: SKU销量占比阈值
        
    Returns:
        Dict: 评估结果
    """
    # 确保索引一致
    actual = actual.reindex(index=pred.index, fill_value=0)
    
    # 计算总销量
    total_actual_sales = actual.sum().sum()
    total_pred_sales = pred.sum().sum()
    
    # 计算每个SKU的指标
    sku_metrics = {}
    for sku in actual.columns:
        actual_sales = actual[sku]
        pred_sales = pred[sku]
        
        # 计算WMAPE
        wmape = calculate_wmape_optimized(actual_sales, pred_sales)
        
        # 计算SKU销量占比
        sku_total_sales = actual_sales.sum()
        sku_weight = sku_total_sales / total_actual_sales if total_actual_sales > 0 else 0
        
        # 仅评估销量占比超过阈值的SKU
        if sku_weight < sku_accuracy_threshold:
            continue
        
        # 计算其他指标
        mape = calculate_mape_optimized(actual_sales, pred_sales)
        mae = calculate_mae_optimized(actual_sales, pred_sales)
        rmse = calculate_rmse_optimized(actual_sales, pred_sales)
        
        sku_metrics[sku] = {
            'wmape': round(wmape, 4),
            'mape': round(mape, 4),
            'mae': round(mae, 2),
            'rmse': round(rmse, 2),
            'total_sales': float(sku_total_sales),
            'weight_in_spu': round(sku_weight, 4)
        }
    
    # 计算总体指标
    total_wmape = calculate_wmape_optimized(actual.values.flatten(), pred.values.flatten())
    
    return {
        'wmape': round(total_wmape, 4),
        'total_actual_sales': float(total_actual_sales),
        'total_pred_sales': float(total_pred_sales),
        'sku_count': len(sku_metrics),
        'sku_metrics': sku_metrics
    }


def calculate_wmape_optimized(actual: pd.Series, pred: pd.Series) -> float:
    """
    优化的WMAPE计算
    
    Args:
        actual: 实际值序列
        pred: 预测值序列
        
    Returns:
        float: WMAPE值
    """
    # 向量化计算
    abs_diff = np.abs(actual.values - pred.values)
    actual_values = actual.values
    
    # 避免除以零
    mask = actual_values > 0
    if not mask.any():
        return 0.0
    
    wmape = np.sum(abs_diff[mask]) / np.sum(actual_values[mask])
    return float(wmape)


def calculate_mape_optimized(actual: pd.Series, pred: pd.Series) -> float:
    """
    优化的MAPE计算
    
    Args:
        actual: 实际值序列
        pred: 预测值序列
        
    Returns:
        float: MAPE值
    """
    # 向量化计算
    abs_diff = np.abs(actual.values - pred.values)
    actual_values = actual.values
    
    # 避免除以零
    mask = actual_values > 0
    if not mask.any():
        return 0.0
    
    ape = abs_diff[mask] / actual_values[mask]
    mape = np.mean(ape)
    return float(mape)


def calculate_mae_optimized(actual: pd.Series, pred: pd.Series) -> float:
    """
    优化的MAE计算
    
    Args:
        actual: 实际值序列
        pred: 预测值序列
        
    Returns:
        float: MAE值
    """
    # 向量化计算
    mae = np.mean(np.abs(actual.values - pred.values))
    return float(mae)


def calculate_rmse_optimized(actual: pd.Series, pred: pd.Series) -> float:
    """
    优化的RMSE计算
    
    Args:
        actual: 实际值序列
        pred: 预测值序列
        
    Returns:
        float: RMSE值
    """
    # 向量化计算
    mse = np.mean((actual.values - pred.values) ** 2)
    rmse = np.sqrt(mse)
    return float(rmse)


def optimize_sku_accuracy_threshold(
    actual: pd.DataFrame, 
    pred: pd.DataFrame,
    threshold_range: List[float] = None
) -> Dict[str, Any]:
    """
    优化SKU准确性阈值
    
    Args:
        actual: 实际销量DataFrame
        pred: 预测销量DataFrame
        threshold_range: 阈值范围
        
    Returns:
        Dict: 优化结果
    """
    if threshold_range is None:
        threshold_range = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]
    
    results = []
    
    for threshold in threshold_range:
        # 计算评估指标
        metrics = calculate_sku_accuracy_optimized(actual, pred, threshold)
        
        # 计算有效SKU数量
        effective_sku_count = len(metrics['sku_metrics'])
        
        # 计算平均WMAPE
        avg_wmape = 0.0
        if metrics['sku_metrics']:
            avg_wmape = np.mean([m['wmape'] for m in metrics['sku_metrics'].values()])
        
        results.append({
            'threshold': threshold,
            'effective_sku_count': effective_sku_count,
            'avg_wmape': round(avg_wmape, 4),
            'total_sales': metrics['total_actual_sales']
        })
    
    # 找到最佳阈值
    best_threshold = min(results, key=lambda x: x['avg_wmape'] if x['effective_sku_count'] > 0 else float('inf'))
    
    return {
        'threshold_range': threshold_range,
        'results': results,
        'best_threshold': best_threshold['threshold'],
        'best_avg_wmape': best_threshold['avg_wmape'],
        'best_effective_sku_count': best_threshold['effective_sku_count']
    }


def calculate_sku_accuracy_trend(
    actual_history: List[pd.DataFrame],
    pred_history: List[pd.DataFrame]
) -> Dict[str, Any]:
    """
    计算SKU准确性趋势
    
    Args:
        actual_history: 历史实际销量列表
        pred_history: 历史预测销量列表
        
    Returns:
        Dict: 趋势分析结果
    """
    if len(actual_history) != len(pred_history):
        raise ValueError("历史数据长度不匹配")
    
    if len(actual_history) == 0:
        return {'trend': 'no_data', 'metrics': []}
    
    # 计算每个时间点的指标
    metrics = []
    for i, (actual, pred) in enumerate(zip(actual_history, pred_history)):
        # 计算评估指标
        result = calculate_sku_accuracy_optimized(actual, pred)
        
        metrics.append({
            'time_index': i,
            'wmape': result['wmape'],
            'sku_count': result['sku_count'],
            'total_sales': result['total_actual_sales']
        })
    
    # 计算趋势
    if len(metrics) >= 2:
        recent_wmape = metrics[-1]['wmape']
        previous_wmape = metrics[-2]['wmape']
        
        if recent_wmape > previous_wmape:
            trend = 'increasing'
            change_pct = (recent_wmape - previous_wmape) / previous_wmape
        else:
            trend = 'decreasing'
            change_pct = (previous_wmape - recent_wmape) / previous_wmape
        
        # 计算7期移动平均
        wmape_values = [m['wmape'] for m in metrics]
        if len(wmape_values) >= 7:
            ma7 = np.mean(wmape_values[-7:])
        else:
            ma7 = np.mean(wmape_values)
        
        return {
            'trend': trend,
            'change_pct': round(change_pct, 4),
            'recent_wmape': recent_wmape,
            'previous_wmape': previous_wmape,
            'ma7': round(ma7, 4),
            'metrics': metrics
        }
    
    return {
        'trend': 'insufficient_data',
        'metrics': metrics
    }


def generate_sku_accuracy_report(
    actual: pd.DataFrame,
    pred: pd.DataFrame,
    threshold: float = 0.01
) -> str:
    """
    生成SKU准确性报告
    
    Args:
        actual: 实际销量DataFrame
        pred: 预测销量DataFrame
        threshold: SKU销量占比阈值
        
    Returns:
        str: 报告字符串
    """
    # 计算评估指标
    result = calculate_sku_accuracy_optimized(actual, pred, threshold)
    
    # 生成报告
    report = f"""
=== SKU准确性评估报告 ===
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

=== 摘要 ===
- 总实际销量: {result['total_actual_sales']:.0f}
- 总预测销量: {result['total_pred_sales']:.0f}
- SKU数量: {result['sku_count']}
- WMAPE: {result['wmape']:.2%}

=== SKU详细指标 ===
"""
    
    # 按WMAPE排序
    sorted_skus = sorted(
        result['sku_metrics'].items(), 
        key=lambda x: x[1]['wmape']
    )
    
    for sku, metrics in sorted_skus[:10]:  # 只显示前10个
        report += f"""
SKU {sku}:
  - WMAPE: {metrics['wmape']:.2%}
  - MAPE: {metrics['mape']:.2%}
  - MAE: {metrics['mae']:.2f}
  - RMSE: {metrics['rmse']:.2f}
  - 总销量: {metrics['total_sales']:.0f}
  - 权重: {metrics['weight_in_spu']:.2%}
"""
    
    if len(sorted_skus) > 10:
        report += f"\n... 还有 {len(sorted_skus) - 10} 个SKU\n"
    
    return report


def main():
    """主函数"""
    # 生成示例数据
    dates = pd.date_range('2026-01-01', periods=10, freq='W')
    
    actual = pd.DataFrame({
        'SKU001': np.random.randint(10, 100, 10),
        'SKU002': np.random.randint(20, 200, 10),
        'SKU003': np.random.randint(15, 150, 10)
    }, index=dates)
    
    pred = pd.DataFrame({
        'SKU001': np.random.randint(10, 100, 10) + np.random.randint(-10, 10, 10),
        'SKU002': np.random.randint(20, 200, 10) + np.random.randint(-20, 20, 10),
        'SKU003': np.random.randint(15, 150, 10) + np.random.randint(-15, 15, 10)
    }, index=dates)
    
    # 计算评估指标
    result = calculate_sku_accuracy_optimized(actual, pred, threshold=0.01)
    
    # 生成报告
    report = generate_sku_accuracy_report(actual, pred, threshold=0.01)
    print(report)
    
    # 优化阈值
    threshold_optimization = optimize_sku_accuracy_threshold(actual, pred)
    print(f"\n最佳阈值: {threshold_optimization['best_threshold']}")
    
    return result


if __name__ == '__main__':
    main()
