"""
预测误差自动报警模块
用于实现预测误差自动报警机制
"""

import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text


class ErrorAlertManager:
    """预测误差自动报警管理器"""
    
    def __init__(self, db_url: str, wmape_threshold: float = 0.30, 
                 alert_config: Optional[Dict[str, Any]] = None):
        """
        初始化误差报警管理器
        
        Args:
            db_url: 数据库连接URL
            wmape_threshold: WMAPE阈值，默认30%
            alert_config: 告警配置
        """
        self.db_url = db_url
        self.wmape_threshold = wmape_threshold
        self.alert_config = alert_config or {}
        
        self.engine = create_engine(db_url)
        self.logger = logging.getLogger('forecasting')
        
        self.logger.info(f"ErrorAlertManager initialized with WMAPE threshold: {wmape_threshold}")
    
    def __del__(self):
        """清理资源"""
        if hasattr(self, 'engine'):
            self.engine.dispose()
            self.logger.info("Database engine disposed")
    
    def configure_threshold(self, spu: str, threshold: float):
        """
        配置SPU的阈值
        
        Args:
            spu: SPU编号
            threshold: WMAPE阈值
        """
        if 'thresholds' not in self.alert_config:
            self.alert_config['thresholds'] = {}
        
        self.alert_config['thresholds'][spu] = threshold
        self.logger.info(f"配置SPU {spu} 的阈值: {threshold}")
    
    def check_wmape_threshold(self, spu: str, wmape: float) -> Optional[Dict[str, Any]]:
        """
        检查WMAPE是否超过阈值
        
        Args:
            spu: SPU编号
            wmape: WMAPE值
            
        Returns:
            Dict: 告警信息，如果没有告警则返回None
        """
        # 获取SPU的阈值
        threshold = self.alert_config.get('thresholds', {}).get(spu, self.wmape_threshold)
        
        if wmape > threshold:
            alert = {
                'alert_id': f"WMAPE_ALERT_{spu}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'alert_type': 'WMAPE_THRESHOLD_EXCEEDED',
                'spu': spu,
                'severity': 'HIGH',
                'message': f"SPU {spu} WMAPE {wmape:.2%} 超过阈值 {threshold:.2%}",
                'details': {
                    'wmape': wmape,
                    'threshold': threshold,
                    'exceeded_by': wmape - threshold,
                    'exceeded_by_pct': (wmape - threshold) / threshold * 100
                },
                'created_at': datetime.now(),
                'status': 'new'
            }
            
            self.logger.warning(f"WMAPE告警: {alert['message']}")
            return alert
        
        return None
    
    def check_wmape_high(self, spu: str, wmape: float, 
                        mean_wmape: float, std_wmape: float) -> Optional[Dict[str, Any]]:
        """
        检查WMAPE是否异常高
        
        Args:
            spu: SPU编号
            wmape: WMAPE值
            mean_wmape: 平均WMAPE
            std_wmape: WMAPE标准差
            
        Returns:
            Dict: 告警信息，如果没有告警则返回None
        """
        # 计算异常高阈值（平均值+3倍标准差）
        high_threshold = mean_wmape + 3 * std_wmape
        
        if wmape > high_threshold and wmape <= self.wmape_threshold:
            alert = {
                'alert_id': f"WMAPE_HIGH_ALERT_{spu}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'alert_type': 'WMAPE_HIGH',
                'spu': spu,
                'severity': 'MEDIUM',
                'message': f"SPU {spu} WMAPE {wmape:.2%} 显著高于平均值 {mean_wmape:.2%}",
                'details': {
                    'wmape': wmape,
                    'mean_wmape': mean_wmape,
                    'std_wmape': std_wmape,
                    'high_threshold': high_threshold,
                    'deviation': (wmape - mean_wmape) / std_wmape
                },
                'created_at': datetime.now(),
                'status': 'new'
            }
            
            self.logger.warning(f"WMAPE高告警: {alert['message']}")
            return alert
        
        return None
    
    def check_consecutive_threshold(self, spu: str, wmape: float, 
                                   recent_wmapes: List[float]) -> Optional[Dict[str, Any]]:
        """
        检查连续WMAPE超阈值
        
        Args:
            spu: SPU编号
            wmape: 当前WMAPE值
            recent_wmapes: 最近WMAPE列表
            
        Returns:
            Dict: 告警信息，如果没有告警则返回None
        """
        # 检查最近N次是否都超阈值
        consecutive_threshold = self.alert_config.get('consecutive_threshold', 3)
        
        if wmape > self.wmape_threshold:
            consecutive_count = sum(1 for w in recent_wmapes[-consecutive_threshold:] if w > self.wmape_threshold)
            
            if consecutive_count >= consecutive_threshold:
                alert = {
                    'alert_id': f"WMAPE_CONSECUTIVE_ALERT_{spu}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    'alert_type': 'WMAPE_CONSECUTIVE_THRESHOLD',
                    'spu': spu,
                    'severity': 'HIGH',
                    'message': f"SPU {spu} 连续 {consecutive_count} 次 WMAPE 超过阈值",
                    'details': {
                        'consecutive_count': consecutive_count,
                        'threshold': consecutive_threshold,
                        'recent_wmapes': recent_wmapes[-consecutive_threshold:]
                    },
                    'created_at': datetime.now(),
                    'status': 'new'
                }
                
                self.logger.warning(f"连续WMAPE告警: {alert['message']}")
                return alert
        
        return None
    
    def check_spu_wmape(self, spu: str, wmape: float, 
                       historical_wmapes: List[float]) -> List[Dict[str, Any]]:
        """
        检查SPU的WMAPE告警
        
        Args:
            spu: SPU编号
            wmape: 当前WMAPE值
            historical_wmapes: 历史WMAPE列表
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        # 检查WMAPE阈值
        threshold_alert = self.check_wmape_threshold(spu, wmape)
        if threshold_alert:
            alerts.append(threshold_alert)
        
        # 检查WMAPE异常高
        if len(historical_wmapes) >= 2:
            mean_wmape = np.mean(historical_wmapes)
            std_wmape = np.std(historical_wmapes)
            
            if std_wmape > 0:  # 避免除以零
                high_alert = self.check_wmape_high(spu, wmape, mean_wmape, std_wmape)
                if high_alert:
                    alerts.append(high_alert)
        
        # 检查连续超阈值
        if len(historical_wmapes) >= 2:
            consecutive_alert = self.check_consecutive_threshold(spu, wmape, historical_wmapes)
            if consecutive_alert:
                alerts.append(consecutive_alert)
        
        return alerts
    
    def check_sku_wmape(self, spu: str, sku_metrics: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检查SKU的WMAPE告警
        
        Args:
            spu: SPU编号
            sku_metrics: SKU指标字典
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        for sku, metrics in sku_metrics.items():
            sku_wmape = metrics.get('wmape', 0)
            sku_threshold = self.alert_config.get('sku_thresholds', {}).get(sku, self.wmape_threshold)
            
            if sku_wmape > sku_threshold:
                alert = {
                    'alert_id': f"SKU_WMAPE_ALERT_{spu}_{sku}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    'alert_type': 'SKU_WMAPE_THRESHOLD_EXCEEDED',
                    'spu': spu,
                    'sku': sku,
                    'severity': 'MEDIUM',
                    'message': f"SKU {sku} WMAPE {sku_wmape:.2%} 超过阈值 {sku_threshold:.2%}",
                    'details': {
                        'wmape': sku_wmape,
                        'threshold': sku_threshold,
                        'total_sales': metrics.get('total_sales', 0),
                        'weight_in_spu': metrics.get('weight_in_spu', 0)
                    },
                    'created_at': datetime.now(),
                    'status': 'new'
                }
                
                self.logger.warning(f"SKU WMAPE告警: {alert['message']}")
                alerts.append(alert)
        
        return alerts
    
    def check_model_performance(self, spu: str, model_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检查模型性能告警
        
        Args:
            spu: SPU编号
            model_results: 模型结果列表
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        if len(model_results) < 2:
            return alerts
        
        # 找出最差模型
        worst_model = max(model_results, key=lambda x: x['wmape'])
        best_model = min(model_results, key=lambda x: x['wmape'])
        
        # 检查最差模型是否比最佳模型差太多
        performance_gap = (worst_model['wmape'] - best_model['wmape']) / best_model['wmape']
        
        if performance_gap > 0.5:  # 最差模型比最佳模型差50%
            alert = {
                'alert_id': f"MODEL_PERFORMANCE_ALERT_{spu}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'alert_type': 'MODEL_PERFORMANCE_GAP',
                'spu': spu,
                'severity': 'MEDIUM',
                'message': f"模型性能差距过大: 最差 {worst_model['algo']} WMAPE {worst_model['wmape']:.2%} vs 最佳 {best_model['algo']} WMAPE {best_model['wmape']:.2%}",
                'details': {
                    'worst_model': worst_model['algo'],
                    'worst_wmape': worst_model['wmape'],
                    'best_model': best_model['algo'],
                    'best_wmape': best_model['wmape'],
                    'performance_gap': performance_gap
                },
                'created_at': datetime.now(),
                'status': 'new'
            }
            
            self.logger.warning(f"模型性能告警: {alert['message']}")
            alerts.append(alert)
        
        return alerts
    
    def check_all(self, spu: str, wmape: float, historical_wmapes: List[float],
                 sku_metrics: Dict[str, Dict[str, Any]], 
                 model_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检查所有告警
        
        Args:
            spu: SPU编号
            wmape: 当前WMAPE值
            historical_wmapes: 历史WMAPE列表
            sku_metrics: SKU指标字典
            model_results: 模型结果列表
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        # 检查SPU告警
        spu_alerts = self.check_spu_wmape(spu, wmape, historical_wmapes)
        alerts.extend(spu_alerts)
        
        # 检查SKU告警
        sku_alerts = self.check_sku_wmape(spu, sku_metrics)
        alerts.extend(sku_alerts)
        
        # 检查模型性能告警
        model_alerts = self.check_model_performance(spu, model_results)
        alerts.extend(model_alerts)
        
        return alerts
    
    def save_alerts_to_db(self, alerts: List[Dict[str, Any]]) -> int:
        """
        保存告警到数据库
        
        Args:
            alerts: 告警列表
            
        Returns:
            int: 保存的告警数量
        """
        if not alerts:
            self.logger.info("没有告警需要保存")
            return 0
        
        try:
            with self.engine.connect() as conn:
                for alert in alerts:
                    query = text("""
                        INSERT INTO forecasting_alerts 
                        (alert_id, alert_type, spu, severity, message, details, created_at, status)
                        VALUES (:alert_id, :alert_type, :spu, :severity, :message, :details, :created_at, :status)
                        ON CONFLICT (alert_id) DO NOTHING
                    """)
                    conn.execute(query, {
                        'alert_id': alert['alert_id'],
                        'alert_type': alert['alert_type'],
                        'spu': alert['spu'],
                        'severity': alert['severity'],
                        'message': alert['message'],
                        'details': str(alert.get('details', {})),
                        'created_at': alert['created_at'],
                        'status': alert.get('status', 'new')
                    })
                conn.commit()
            
            self.logger.info(f"保存 {len(alerts)} 个告警到数据库")
            return len(alerts)
        except Exception as e:
            self.logger.error(f"保存告警到数据库失败: {str(e)}")
            return 0
    
    def run_error_alerts(self, spu: str, wmape: float, historical_wmapes: List[float],
                        sku_metrics: Dict[str, Dict[str, Any]], 
                        model_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        运行误差报警
        
        Args:
            spu: SPU编号
            wmape: 当前WMAPE值
            historical_wmapes: 历史WMAPE列表
            sku_metrics: SKU指标字典
            model_results: 模型结果列表
            
        Returns:
            Dict: 报告结果
        """
        # 检查所有告警
        alerts = self.check_all(spu, wmape, historical_wmapes, sku_metrics, model_results)
        
        # 保存告警
        saved_count = self.save_alerts_to_db(alerts)
        
        # 生成报告
        report = {
            'spu': spu,
            'wmape': wmape,
            'historical_wmapes': historical_wmapes,
            'alerts': alerts,
            'alerts_saved': saved_count,
            'summary': {
                'total_alerts': len(alerts),
                'high_severity_count': len([a for a in alerts if a['severity'] == 'HIGH']),
                'medium_severity_count': len([a for a in alerts if a['severity'] == 'MEDIUM']),
                'by_type': {}
            }
        }
        
        # 按类型统计
        for alert in alerts:
            alert_type = alert['alert_type']
            if alert_type not in report['summary']['by_type']:
                report['summary']['by_type'][alert_type] = 0
            report['summary']['by_type'][alert_type] += 1
        
        return report


def main():
    """主函数"""
    # 从环境变量获取数据库URL
    db_url = os.environ.get('DATABASE_URL', 'postgresql://user:password@localhost:5432/dbname')
    
    # 创建误差报警管理器
    alert_manager = ErrorAlertManager(
        db_url=db_url,
        wmape_threshold=0.30,
        alert_config={
            'thresholds': {
                'SPU001': 0.25,  # 特定SPU的阈值
            },
            'sku_thresholds': {
                'SKU001': 0.20,  # 特定SKU的阈值
            },
            'consecutive_threshold': 3  # 连续超阈值次数
        }
    )
    
    # 模拟数据
    spu = 'SPU001'
    wmape = 0.45
    historical_wmapes = [0.15, 0.18, 0.20, 0.22, 0.25]
    sku_metrics = {
        'SKU001': {'wmape': 0.12, 'total_sales': 1000, 'weight_in_spu': 0.3},
        'SKU002': {'wmape': 0.48, 'total_sales': 1500, 'weight_in_spu': 0.4},
        'SKU003': {'wmape': 0.18, 'total_sales': 1200, 'weight_in_spu': 0.3}
    }
    model_results = [
        {'algo': 'Prophet', 'wmape': 0.15, 'mape': 0.12, 'mae': 50.2},
        {'algo': 'XGBoost', 'wmape': 0.48, 'mape': 0.45, 'mae': 120.3},
        {'algo': 'LightGBM', 'wmape': 0.20, 'mape': 0.18, 'mae': 60.1}
    ]
    
    # 运行误差报警
    report = alert_manager.run_error_alerts(spu, wmape, historical_wmapes, sku_metrics, model_results)
    
    # 打印报告
    print(f"\n=== 误差报警报告 ===")
    print(f"SPU: {report['spu']}")
    print(f"WMAPE: {report['wmape']:.2%}")
    print(f"告警数量: {report['summary']['total_alerts']}")
    print(f"高严重级别: {report['summary']['high_severity_count']}")
    print(f"中严重级别: {report['summary']['medium_severity_count']}")
    print(f"\n告警详情:")
    for alert in report['alerts']:
        print(f"- [{alert['severity']}] {alert['message']}")
    
    return report


if __name__ == '__main__':
    main()
