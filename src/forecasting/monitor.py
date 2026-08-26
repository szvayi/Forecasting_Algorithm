"""
预测准确性监控模块
用于监控预测准确性，实现WMAPE阈值监控、误差趋势分析和告警机制
"""

import os
import datetime
import logging
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/forecasting_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ForecastingMonitor:
    """预测准确性监控器"""
    
    def __init__(self, db_url: str, wmape_threshold: float = 0.30):
        """
        初始化监控器
        
        Args:
            db_url: 数据库连接URL
            wmape_threshold: WMAPE阈值，默认30%
        """
        self.db_url = db_url
        self.wmape_threshold = wmape_threshold
        self._engine = None
        logger.info(f"ForecastingMonitor initialized with WMAPE threshold: {wmape_threshold}")

    def __del__(self):
        """清理资源"""
        if getattr(self, '_engine', None) is not None:
            self._engine.dispose()
            logger.info("Database engine disposed")

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_engine(self.db_url)
        return self._engine
    
    def load_forecast_history(self, days: int = 30) -> pd.DataFrame:
        """
        加载预测历史数据
        
        Args:
            days: 加载最近N天的数据
            
        Returns:
            pd.DataFrame: 预测历史数据
        """
        query = text("""
        SELECT 
            spu,
            run_date,
            forecast_target_date,
            winner_algo,
            validation_wmape,
            sku_accuracy_json,
            sku_share_json,
            best_params,
            training_weeks,
            data_end_date
        FROM finedatalink.sales_forecast_history
        WHERE run_date >= (CURRENT_DATE - (:days * INTERVAL '1 day'))
        ORDER BY run_date DESC, spu
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"days": days})
                if isinstance(result, pd.DataFrame):
                    df = result.copy()
                else:
                    rows = result.mappings().all()
                    df = pd.DataFrame(rows)
            logger.info(f"Loaded {len(df)} forecast records from last {days} days")
            return df
        except Exception as e:
            logger.error(f"Failed to load forecast history: {str(e)}")
            raise
    
    def calculate_wmape_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        计算WMAPE统计信息
        
        Args:
            df: 预测历史数据
            
        Returns:
            Dict: WMAPE统计信息
        """
        stats = {
            'overall': {
                'mean': df['validation_wmape'].mean(),
                'median': df['validation_wmape'].median(),
                'std': df['validation_wmape'].std(),
                'min': df['validation_wmape'].min(),
                'max': df['validation_wmape'].max(),
                'threshold_exceeded_count': (df['validation_wmape'] > self.wmape_threshold).sum(),
                'threshold_exceeded_rate': (df['validation_wmape'] > self.wmape_threshold).mean()
            },
            'by_spu': {},
            'by_date': {},
            'by_model': {}
        }
        
        # 按SPU统计
        for spu in df['spu'].unique():
            spu_data = df[df['spu'] == spu]
            stats['by_spu'][spu] = {
                'count': len(spu_data),
                'mean_wmape': spu_data['validation_wmape'].mean(),
                'median_wmape': spu_data['validation_wmape'].median(),
                'max_wmape': spu_data['validation_wmape'].max(),
                'threshold_exceeded': (spu_data['validation_wmape'] > self.wmape_threshold).sum()
            }
        
        # 按日期统计
        for date in df['run_date'].unique():
            date_data = df[df['run_date'] == date]
            date_key = str(pd.Timestamp(date).date())
            stats['by_date'][date_key] = {
                'count': len(date_data),
                'mean_wmape': date_data['validation_wmape'].mean(),
                'threshold_exceeded': (date_data['validation_wmape'] > self.wmape_threshold).sum()
            }
        
        # 按模型统计
        for model in df['winner_algo'].unique():
            model_data = df[df['winner_algo'] == model]
            stats['by_model'][model] = {
                'count': len(model_data),
                'mean_wmape': model_data['validation_wmape'].mean(),
                'median_wmape': model_data['validation_wmape'].median(),
                'threshold_exceeded': (model_data['validation_wmape'] > self.wmape_threshold).sum()
            }
        
        logger.info(f"Calculated WMAPE statistics for {len(df)} records")
        return stats
    
    def detect_anomalies(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        检测异常预测
        
        Args:
            df: 预测历史数据
            
        Returns:
            List[Dict]: 异常预测列表
        """
        anomalies = []
        
        # 检测WMAPE超阈值
        threshold_exceeded = df[df['validation_wmape'] > self.wmape_threshold]
        for _, row in threshold_exceeded.iterrows():
            anomalies.append({
                'type': 'WMAPE_THRESHOLD_EXCEEDED',
                'spu': row['spu'],
                'run_date': row['run_date'],
                'value': row['validation_wmape'],
                'threshold': self.wmape_threshold,
                'message': f"SPU {row['spu']} WMAPE {row['validation_wmape']:.2%} exceeds threshold {self.wmape_threshold:.2%}"
            })
        
        # 检测WMAPE异常高（超过平均值3倍标准差）
        mean_wmape = df['validation_wmape'].mean()
        std_wmape = df['validation_wmape'].std()
        upper_bound = mean_wmape + 3 * std_wmape
        high_wmape = df[df['validation_wmape'] > upper_bound]
        
        for _, row in high_wmape.iterrows():
            if row['validation_wmape'] <= self.wmape_threshold:  # 避免重复
                anomalies.append({
                    'type': 'WMAPE_HIGH',
                    'spu': row['spu'],
                    'run_date': row['run_date'],
                    'value': row['validation_wmape'],
                    'mean': mean_wmape,
                    'std': std_wmape,
                    'upper_bound': upper_bound,
                    'message': f"SPU {row['spu']} WMAPE {row['validation_wmape']:.2%} is significantly higher than average {mean_wmape:.2%}"
                })
        
        logger.info(f"Detected {len(anomalies)} anomalies")
        return anomalies
    
    def analyze_trends(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        分析趋势
        
        Args:
            df: 预测历史数据
            
        Returns:
            Dict: 趋势分析结果
        """
        trends = {
            'wmape_trend': {},
            'model_performance_trend': {}
        }
        
        # WMAPE趋势分析
        daily_wmape = df.groupby('run_date')['validation_wmape'].mean()
        if len(daily_wmape) >= 2:
            # 计算7天移动平均
            ma7 = daily_wmape.rolling(window=7).mean()
            
            # 计算趋势
            if len(ma7) >= 2:
                recent_ma = ma7.iloc[-1]
                previous_ma = ma7.iloc[-2]
                trend = 'increasing' if recent_ma > previous_ma else 'decreasing'
                change_pct = (recent_ma - previous_ma) / previous_ma if previous_ma > 0 else 0
                
                trends['wmape_trend'] = {
                    'recent_ma': recent_ma,
                    'previous_ma': previous_ma,
                    'trend': trend,
                    'change_pct': change_pct,
                    'message': f"WMAPE trend is {trend} by {change_pct:.2%}"
                }
            else:
                trends['wmape_trend'] = {
                    'recent_ma': daily_wmape.iloc[-1],
                    'message': "Insufficient data for trend analysis"
                }
        
        # 模型性能趋势
        for model in df['winner_algo'].unique():
            model_data = df[df['winner_algo'] == model].groupby('run_date')['validation_wmape'].mean()
            if len(model_data) >= 2:
                recent_wmape = model_data.iloc[-1]
                previous_wmape = model_data.iloc[-2]
                change = recent_wmape - previous_wmape
                trends['model_performance_trend'][model] = {
                    'recent_wmape': recent_wmape,
                    'previous_wmape': previous_wmape,
                    'change': change,
                    'improving': change < 0
                }
        
        logger.info("Completed trend analysis")
        return trends
    
    def generate_alerts(self, anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        生成告警
        
        Args:
            anomalies: 异常列表
            
        Returns:
            List[Dict]: 告警列表
        """
        alerts = []
        
        for anomaly in anomalies:
            run_date = pd.Timestamp(anomaly['run_date'])
            alert = {
                'alert_id': f"ALERT_{anomaly['type']}_{anomaly['spu']}_{run_date.date()}",
                'alert_type': anomaly['type'],
                'spu': anomaly['spu'],
                'run_date': run_date,
                'severity': 'HIGH' if 'THRESHOLD' in anomaly['type'] else 'MEDIUM',
                'message': anomaly['message'],
                'created_at': datetime.datetime.now()
            }
            alerts.append(alert)
        
        logger.info(f"Generated {len(alerts)} alerts")
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
            logger.info("No alerts to save")
            return 0
        
        try:
            with self.engine.connect() as conn:
                for alert in alerts:
                    query = text("""
                        INSERT INTO forecasting_alerts 
                        (alert_id, alert_type, spu, run_date, severity, message, created_at)
                        VALUES (:alert_id, :alert_type, :spu, :run_date, :severity, :message, :created_at)
                        ON CONFLICT (alert_id) DO NOTHING
                    """)
                    conn.execute(query, alert)
                conn.commit()
            
            logger.info(f"Saved {len(alerts)} alerts to database")
            return len(alerts)
        except Exception as e:
            logger.error(f"Failed to save alerts to database: {str(e)}")
            raise
    
    def run_monitoring(self, days: int = 30) -> Dict[str, Any]:
        """
        运行监控
        
        Args:
            days: 加载最近N天的数据
            
        Returns:
            Dict: 监控结果
        """
        logger.info(f"Starting monitoring for last {days} days")
        
        # 加载数据
        df = self.load_forecast_history(days)
        
        # 计算统计信息
        stats = self.calculate_wmape_statistics(df)
        
        # 检测异常
        anomalies = self.detect_anomalies(df)
        
        # 分析趋势
        trends = self.analyze_trends(df)
        
        # 生成告警
        alerts = self.generate_alerts(anomalies)
        
        # 保存告警
        saved_count = self.save_alerts_to_db(alerts)
        
        result = {
            'summary': {
                'total_records': len(df),
                'threshold_exceeded_count': stats['overall']['threshold_exceeded_count'],
                'anomaly_count': len(anomalies),
                'alert_count': len(alerts),
                'alerts_saved': saved_count
            },
            'stats': stats,
            'anomalies': anomalies,
            'trends': trends,
            'alerts': alerts
        }
        
        logger.info(f"Monitoring completed. Summary: {result['summary']}")
        return result
    
    def get_monitoring_report(self, days: int = 30) -> str:
        """
        获取监控报告
        
        Args:
            days: 加载最近N天的数据
            
        Returns:
            str: 监控报告
        """
        result = self.run_monitoring(days)
        
        report = f"""
=== 预测准确性监控报告 ===
生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
监控周期: 最近{days}天

=== 摘要 ===
- 总记录数: {result['summary']['total_records']}
- WMAPE超阈值次数: {result['summary']['threshold_exceeded_count']}
- 异常检测数量: {result['summary']['anomaly_count']}
- 生成告警数量: {result['summary']['alert_count']}
- 已保存告警数量: {result['summary']['alerts_saved']}

=== WMAPE统计 ===
- 平均WMAPE: {result['stats']['overall']['mean']:.2%}
- 中位数WMAPE: {result['stats']['overall']['median']:.2%}
- 标准差: {result['stats']['overall']['std']:.4f}
- 最小WMAPE: {result['stats']['overall']['min']:.2%}
- 最大WMAPE: {result['stats']['overall']['max']:.2%}
- 超阈值比例: {result['stats']['overall']['threshold_exceeded_rate']:.2%}

=== 趋势分析 ===
{result['trends']['wmape_trend'].get('message', '无趋势数据')}

=== 异常详情 ===
"""
        
        for anomaly in result['anomalies'][:10]:  # 只显示前10个
            report += f"- {anomaly['message']}\n"
        
        if len(result['anomalies']) > 10:
            report += f"... 还有 {len(result['anomalies']) - 10} 个异常\n"
        
        report += f"""
=== 告警详情 ===
"""
        
        for alert in result['alerts'][:10]:  # 只显示前10个
            report += f"- [{alert['severity']}] {alert['message']}\n"
        
        if len(result['alerts']) > 10:
            report += f"... 还有 {len(result['alerts']) - 10} 个告警\n"
        
        return report


def main():
    """主函数"""
    # 从环境变量获取数据库URL
    db_url = os.environ.get('DATABASE_URL', 'postgresql://user:password@localhost:5432/dbname')
    
    # 创建监控器
    monitor = ForecastingMonitor(db_url, wmape_threshold=0.30)
    
    # 运行监控
    result = monitor.run_monitoring(days=30)
    
    # 打印报告
    report = monitor.get_monitoring_report(days=30)
    print(report)
    
    return result


if __name__ == '__main__':
    main()
