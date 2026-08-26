"""
增强的日志记录与告警模块
用于记录详细的运行日志和关键异常告警
"""

import os
import logging
import logging.handlers
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd


class EnhancedLogger:
    """增强的日志记录器"""
    
    def __init__(self, log_dir: str = 'logs', log_level: str = 'INFO'):
        """
        初始化增强日志记录器
        
        Args:
            log_dir: 日志目录
            log_level: 日志级别
        """
        self.log_dir = log_dir
        self.log_level = getattr(logging, log_level.upper())
        
        # 创建日志目录
        os.makedirs(log_dir, exist_ok=True)
        
        # 创建logger
        self.logger = logging.getLogger('forecasting')
        self.logger.setLevel(self.log_level)
        
        # 避免重复添加handler
        if not self.logger.handlers:
            self._setup_handlers()
        
        self.logger.info("EnhancedLogger initialized")
    
    def _setup_handlers(self):
        """设置日志处理器"""
        # 文件处理器 - 详细日志
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self.log_dir, 'forecasting.log'),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'
        )
        file_handler.setFormatter(file_format)
        self.logger.addHandler(file_handler)
        
        # 文件处理器 - 错误日志
        error_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self.log_dir, 'error.log'),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'
        )
        error_handler.setFormatter(error_format)
        self.logger.addHandler(error_handler)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)
    
    def log_forecast_start(self, spu: str, mode: str, exog_cols: Optional[List[str]] = None):
        """记录预测开始"""
        self.logger.info(f"=== 预测开始 ===")
        self.logger.info(f"SPU: {spu}")
        self.logger.info(f"模式: {mode}")
        if exog_cols:
            self.logger.info(f"外生变量: {exog_cols}")
    
    def log_forecast_end(self, spu: str, elapsed_time: float, wmape: float, algo: str):
        """记录预测结束"""
        self.logger.info(f"=== 预测结束 ===")
        self.logger.info(f"SPU: {spu}")
        self.logger.info(f"耗时: {elapsed_time:.2f}秒")
        self.logger.info(f"WMAPE: {wmape:.2%}")
        self.logger.info(f"模型: {algo}")
    
    def log_data_quality(self, spu: str, data_points: int, missing_rate: float, 
                        trend: str, seasonality: str):
        """记录数据质量"""
        self.logger.info(f"=== 数据质量分析 ===")
        self.logger.info(f"SPU: {spu}")
        self.logger.info(f"数据点数: {data_points}")
        self.logger.info(f"缺失率: {missing_rate:.2%}")
        self.logger.info(f"趋势: {trend}")
        self.logger.info(f"季节性: {seasonality}")
    
    def log_model_selection(self, spu: str, models: List[Dict[str, Any]]):
        """记录模型选择"""
        self.logger.info(f"=== 模型竞赛结果 ===")
        self.logger.info(f"SPU: {spu}")
        
        for model in models:
            self.logger.info(
                f"{model['algo']}: WMAPE={model['wmape']:.2%}, "
                f"MAPE={model.get('mape', 0):.2%}, "
                f"MAE={model.get('mae', 0):.2f}"
            )
        
        winner = min(models, key=lambda x: x['wmape'])
        self.logger.info(f"胜出模型: {winner['algo']} (WMAPE={winner['wmape']:.2%})")
    
    def log_sku_prediction(self, spu: str, sku_metrics: Dict[str, Dict[str, Any]]):
        """记录SKU预测"""
        self.logger.info(f"=== SKU预测结果 ===")
        self.logger.info(f"SPU: {spu}")
        
        for sku, metrics in sku_metrics.items():
            self.logger.info(
                f"SKU {sku}: WMAPE={metrics['wmape']:.2%}, "
                f"总销量={metrics['total_sales']:.0f}, "
                f"权重={metrics['weight_in_spu']:.2%}"
            )
    
    def log_error(self, spu: str, error_type: str, error_message: str, 
                 error_details: Optional[Dict[str, Any]] = None):
        """记录错误"""
        self.logger.error(f"=== 错误记录 ===")
        self.logger.error(f"SPU: {spu}")
        self.logger.error(f"错误类型: {error_type}")
        self.logger.error(f"错误消息: {error_message}")
        if error_details:
            for key, value in error_details.items():
                self.logger.error(f"{key}: {value}")
    
    def log_alert(self, alert_type: str, spu: str, severity: str, 
                 message: str, details: Optional[Dict[str, Any]] = None):
        """记录告警"""
        if severity == 'HIGH':
            self.logger.critical(f"=== 高优先级告警 ===")
        else:
            self.logger.warning(f"=== 告警 ===")
        
        self.logger.log(
            logging.CRITICAL if severity == 'HIGH' else logging.WARNING,
            f"告警类型: {alert_type}"
        )
        self.logger.log(
            logging.CRITICAL if severity == 'HIGH' else logging.WARNING,
            f"SPU: {spu}"
        )
        self.logger.log(
            logging.CRITICAL if severity == 'HIGH' else logging.WARNING,
            f"严重级别: {severity}"
        )
        self.logger.log(
            logging.CRITICAL if severity == 'HIGH' else logging.WARNING,
            f"消息: {message}"
        )
        if details:
            for key, value in details.items():
                self.logger.log(
                    logging.CRITICAL if severity == 'HIGH' else logging.WARNING,
                    f"{key}: {value}"
                )
    
    def get_logger(self):
        """获取logger实例"""
        return self.logger


class AlertManager:
    """告警管理器"""
    
    def __init__(self, db_url: Optional[str] = None):
        """
        初始化告警管理器
        
        Args:
            db_url: 数据库连接URL（可选）
        """
        self.db_url = db_url
        self.alerts = []
        self.logger = logging.getLogger('forecasting')
        
        self.logger.info("AlertManager initialized")
    
    def create_alert(self, alert_type: str, spu: str, severity: str, 
                    message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        创建告警
        
        Args:
            alert_type: 告警类型
            spu: SPU编号
            severity: 严重级别
            message: 告警消息
            details: 详细信息
            
        Returns:
            Dict: 告警信息
        """
        alert = {
            'alert_id': f"ALERT_{alert_type}_{spu}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'alert_type': alert_type,
            'spu': spu,
            'severity': severity,
            'message': message,
            'details': details or {},
            'created_at': datetime.now(),
            'status': 'new'
        }
        
        self.alerts.append(alert)
        self.logger.warning(f"告警创建: {alert['alert_id']} - {message}")
        
        return alert
    
    def get_high_severity_alerts(self) -> List[Dict[str, Any]]:
        """获取高严重级别告警"""
        return [alert for alert in self.alerts if alert['severity'] == 'HIGH']
    
    def get_alerts_by_spu(self, spu: str) -> List[Dict[str, Any]]:
        """获取指定SPU的告警"""
        return [alert for alert in self.alerts if alert['spu'] == spu]
    
    def clear_alerts(self):
        """清除所有告警"""
        self.alerts = []
        self.logger.info("所有告警已清除")
    
    def get_alert_summary(self) -> Dict[str, Any]:
        """获取告警摘要"""
        summary = {
            'total_alerts': len(self.alerts),
            'high_severity_count': len(self.get_high_severity_alerts()),
            'by_type': {},
            'by_spu': {}
        }
        
        for alert in self.alerts:
            # 按类型统计
            alert_type = alert['alert_type']
            if alert_type not in summary['by_type']:
                summary['by_type'][alert_type] = 0
            summary['by_type'][alert_type] += 1
            
            # 按SPU统计
            spu = alert['spu']
            if spu not in summary['by_spu']:
                summary['by_spu'][spu] = 0
            summary['by_spu'][spu] += 1
        
        return summary
    
    def save_alerts_to_db(self):
        """保存告警到数据库"""
        if not self.db_url:
            self.logger.warning("数据库URL未配置，告警无法保存到数据库")
            return False
        
        try:
            from sqlalchemy import create_engine, text
            
            engine = create_engine(self.db_url)
            
            with engine.connect() as conn:
                for alert in self.alerts:
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
                        'details': str(alert['details']),
                        'created_at': alert['created_at'],
                        'status': alert['status']
                    })
                conn.commit()
            
            self.logger.info(f"保存 {len(self.alerts)} 个告警到数据库")
            return True
        except Exception as e:
            self.logger.error(f"保存告警到数据库失败: {str(e)}")
            return False


def setup_logging(log_dir: str = 'logs', log_level: str = 'INFO'):
    """
    设置日志
    
    Args:
        log_dir: 日志目录
        log_level: 日志级别
    """
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'forecasting.log')),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger('forecasting')


def main():
    """主函数"""
    # 设置日志
    logger = setup_logging(log_dir='logs', log_level='INFO')
    
    # 创建增强日志记录器
    enhanced_logger = EnhancedLogger(log_dir='logs', log_level='INFO')
    
    # 记录预测开始
    enhanced_logger.log_forecast_start(
        spu='SPU001',
        mode='smart',
        exog_cols=['ad_cost', 'price']
    )
    
    # 记录数据质量
    enhanced_logger.log_data_quality(
        spu='SPU001',
        data_points=100,
        missing_rate=0.05,
        trend='upward',
        seasonality='strong'
    )
    
    # 记录模型选择
    enhanced_logger.log_model_selection(
        spu='SPU001',
        models=[
            {'algo': 'Prophet', 'wmape': 0.15, 'mape': 0.12, 'mae': 50.2},
            {'algo': 'XGBoost', 'wmape': 0.18, 'mape': 0.15, 'mae': 55.3},
            {'algo': 'LightGBM', 'wmape': 0.16, 'mape': 0.13, 'mae': 52.1}
        ]
    )
    
    # 记录SKU预测
    enhanced_logger.log_sku_prediction(
        spu='SPU001',
        sku_metrics={
            'SKU001': {'wmape': 0.12, 'total_sales': 1000, 'weight_in_spu': 0.3},
            'SKU002': {'wmape': 0.15, 'total_sales': 1500, 'weight_in_spu': 0.4},
            'SKU003': {'wmape': 0.18, 'total_sales': 1200, 'weight_in_spu': 0.3}
        }
    )
    
    # 记录预测结束
    enhanced_logger.log_forecast_end(
        spu='SPU001',
        elapsed_time=12.5,
        wmape=0.15,
        algo='Prophet'
    )
    
    # 创建告警管理器
    alert_manager = AlertManager()
    
    # 创建告警
    alert_manager.create_alert(
        alert_type='WMAPE_THRESHOLD_EXCEEDED',
        spu='SPU001',
        severity='HIGH',
        message='SPU SPU001 WMAPE超过阈值',
        details={'wmape': 0.45, 'threshold': 0.30}
    )
    
    # 获取告警摘要
    summary = alert_manager.get_alert_summary()
    print(f"告警摘要: {summary}")
    
    return enhanced_logger, alert_manager


if __name__ == '__main__':
    main()
