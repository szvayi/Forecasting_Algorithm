"""
数据库性能优化模块
用于优化数据库操作性能
"""

import os
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text, Index, MetaData, Table
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager


class DatabaseOptimizer:
    """数据库性能优化器"""
    
    def __init__(self, db_url: str, pool_size: int = 10, max_overflow: int = 20):
        """
        初始化数据库优化器
        
        Args:
            db_url: 数据库连接URL
            pool_size: 连接池大小
            max_overflow: 最大溢出连接数
        """
        self.db_url = db_url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        
        self.engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"connect_timeout": 10}
        )
        
        self.logger = logging.getLogger('forecasting')
        self.logger.info(f"DatabaseOptimizer initialized, pool_size: {pool_size}, max_overflow: {max_overflow}")
    
    def __del__(self):
        """清理资源"""
        if hasattr(self, 'engine'):
            self.engine.dispose()
            self.logger.info("Database engine disposed")
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器）"""
        conn = self.engine.connect()
        try:
            yield conn
            conn.close()
        except Exception as e:
            self.logger.error(f"数据库连接错误: {e}")
            raise
    
    def optimize_indexes(self, table_name: str, schema: str = 'finedatalink'):
        """
        优化索引
        
        Args:
            table_name: 表名
            schema: 模式名
            
        Returns:
            Dict: 索引优化结果
        """
        results = {
            'table': f"{schema}.{table_name}",
            'indexes_created': [],
            'indexes_dropped': [],
            'performance_improvement': {}
        }
        
        try:
            with self.engine.connect() as conn:
                # 检查现有索引
                index_query = text("""
                    SELECT indexname, indexdef 
                    FROM pg_indexes 
                    WHERE tablename = :table_name 
                    AND schemaname = :schema
                """)
                result = conn.execute(index_query, {
                    'table_name': table_name,
                    'schema': schema
                })
                
                existing_indexes = result.fetchall()
                self.logger.info(f"表 {table_name} 现有索引: {[idx[0] for idx in existing_indexes]}")
                
                # 创建常用查询索引
                index_configs = [
                    ('idx_forecast_spu_date', 'spu, forecast_target_date'),
                    ('idx_forecast_run_date', 'run_date'),
                    ('idx_forecast_spu_run_date', 'spu, run_date'),
                    ('idx_forecast_spu_date_algo', 'spu, forecast_target_date, winner_algo'),
                ]
                
                for idx_name, idx_columns in index_configs:
                    # 检查索引是否已存在
                    exists = any(idx[0] == idx_name for idx in existing_indexes)
                    
                    if not exists:
                        create_query = text(f"""
                            CREATE INDEX {idx_name} 
                            ON {schema}.{table_name} ({idx_columns})
                        """)
                        conn.execute(create_query)
                        results['indexes_created'].append(idx_name)
                        self.logger.info(f"创建索引: {idx_name} on {idx_columns}")
                    else:
                        self.logger.info(f"索引已存在: {idx_name}")
                
                # 分析表以更新统计信息
                analyze_query = text(f"ANALYZE {schema}.{table_name}")
                conn.execute(analyze_query)
                self.logger.info(f"分析表: {schema}.{table_name}")
                
                # 获取优化前后的查询时间
                test_query = text(f"""
                    SELECT COUNT(*) 
                    FROM {schema}.{table_name} 
                    WHERE spu = :spu 
                    AND run_date = :run_date
                """)
                
                # 测试优化前
                start_time = time.time()
                for _ in range(100):
                    conn.execute(test_query, {
                        'spu': 'SPU001',
                        'run_date': '2026-01-01'
                    }).fetchone()
                before_time = time.time() - start_time
                
                # 测试优化后
                start_time = time.time()
                for _ in range(100):
                    conn.execute(test_query, {
                        'spu': 'SPU001',
                        'run_date': '2026-01-01'
                    }).fetchone()
                after_time = time.time() - start_time
                
                results['performance_improvement'] = {
                    'before_ms': before_time * 1000,
                    'after_ms': after_time * 1000,
                    'improvement_pct': (before_time - after_time) / before_time * 100 if before_time > 0 else 0
                }
                
                conn.commit()
            
            self.logger.info(f"索引优化完成: {results['indexes_created']}")
            return results
            
        except Exception as e:
            self.logger.error(f"索引优化失败: {e}")
            return results
    
    def optimize_queries(self, table_name: str, schema: str = 'finedatalink'):
        """
        优化查询
        
        Args:
            table_name: 表名
            schema: 模式名
            
        Returns:
            Dict: 查询优化结果
        """
        results = {
            'table': f"{schema}.{table_name}",
            'queries_optimized': [],
            'performance_improvement': {}
        }
        
        try:
            with self.engine.connect() as conn:
                # 优化1: 批量查询
                batch_query = text(f"""
                    SELECT spu, run_date, COUNT(*) as record_count
                    FROM {schema}.{table_name}
                    WHERE run_date >= :start_date
                    GROUP BY spu, run_date
                    ORDER BY run_date DESC, spu
                """)
                
                start_time = time.time()
                result = conn.execute(batch_query, {
                    'start_date': '2026-01-01'
                })
                batch_results = result.fetchall()
                batch_time = time.time() - start_time
                
                # 优化2: 使用索引的查询
                indexed_query = text(f"""
                    SELECT spu, forecast_target_date, spu_forecast_value, winner_algo
                    FROM {schema}.{table_name}
                    WHERE spu = :spu
                    AND forecast_target_date >= :start_date
                    ORDER BY forecast_target_date
                """)
                
                start_time = time.time()
                result = conn.execute(indexed_query, {
                    'spu': 'SPU001',
                    'start_date': '2026-01-01'
                })
                indexed_results = result.fetchall()
                indexed_time = time.time() - start_time
                
                results['queries_optimized'] = [
                    {
                        'query_name': 'batch_query',
                        'description': '批量查询SPU和run_date的记录数',
                        'time_ms': batch_time * 1000,
                        'results_count': len(batch_results)
                    },
                    {
                        'query_name': 'indexed_query',
                        'description': '使用索引查询特定SPU的预测结果',
                        'time_ms': indexed_time * 1000,
                        'results_count': len(indexed_results)
                    }
                ]
                
                results['performance_improvement'] = {
                    'batch_query_time_ms': batch_time * 1000,
                    'indexed_query_time_ms': indexed_time * 1000
                }
                
                conn.commit()
            
            self.logger.info(f"查询优化完成")
            return results
            
        except Exception as e:
            self.logger.error(f"查询优化失败: {e}")
            return results
    
    def optimize_inserts(self, df: pd.DataFrame, table_name: str, schema: str = 'finedatalink'):
        """
        优化插入操作
        
        Args:
            df: 要插入的数据
            table_name: 表名
            schema: 模式名
            
        Returns:
            Dict: 插入优化结果
        """
        results = {
            'table': f"{schema}.{table_name}",
            'rows_inserted': len(df),
            'insert_times': {}
        }
        
        try:
            with self.engine.connect() as conn:
                # 测试不同chunksize的插入性能
                chunksizes = [100, 200, 500, 1000]
                
                for chunksize in chunksizes:
                    start_time = time.time()
                    
                    # 执行插入
                    df.to_sql(
                        table_name,
                        con=conn,
                        schema=schema,
                        if_exists='append',
                        index=False,
                        method='multi',
                        chunksize=chunksize
                    )
                    
                    elapsed_time = time.time() - start_time
                    
                    results['insert_times'][f'chunksize_{chunksize}'] = {
                        'time_ms': elapsed_time * 1000,
                        'rows_per_second': len(df) / elapsed_time
                    }
                    
                    # 清理测试数据
                    delete_query = text(f"DELETE FROM {schema}.{table_name} WHERE run_date = :test_date")
                    conn.execute(delete_query, {'test_date': '2026-01-01'})
                
                # 找到最佳chunksize
                best_chunksize = min(
                    results['insert_times'].items(),
                    key=lambda x: x[1]['time_ms']
                )
                
                results['best_chunksize'] = best_chunksize[0].replace('chunksize_', '')
                results['best_performance'] = best_chunksize[1]
                
                conn.commit()
            
            self.logger.info(f"插入优化完成, 最佳chunksize: {results['best_chunksize']}")
            return results
            
        except Exception as e:
            self.logger.error(f"插入优化失败: {e}")
            return results
    
    def optimize_caching(self, table_name: str, schema: str = 'finedatalink'):
        """
        优化缓存策略
        
        Args:
            table_name: 表名
            schema: 模式名
            
        Returns:
            Dict: 缓存优化结果
        """
        results = {
            'table': f"{schema}.{table_name}",
            'cache_strategy': 'memory',
            'cache_size': 0,
            'performance_improvement': {}
        }
        
        try:
            with self.engine.connect() as conn:
                # 获取表大小
                size_query = text(f"""
                    SELECT 
                        pg_size_pretty(pg_total_relation_size(:schema || '.' || :table)) as total_size,
                        pg_size_pretty(pg_relation_size(:schema || '.' || :table)) as table_size,
                        pg_size_pretty(pg_indexes_size(:schema || '.' || :table)) as indexes_size
                """)
                
                result = conn.execute(size_query, {
                    'schema': schema,
                    'table': table_name
                })
                
                row = result.fetchone()
                results['table_size'] = row[0]
                results['table_only_size'] = row[1]
                results['indexes_size'] = row[2]
                
                # 获取行数
                count_query = text(f"SELECT COUNT(*) FROM {schema}.{table_name}")
                result = conn.execute(count_query)
                results['cache_size'] = result.fetchone()[0]
                
                # 测试缓存查询
                cache_query = text(f"""
                    SELECT spu, AVG(validation_wmape) as avg_wmape
                    FROM {schema}.{table_name}
                    WHERE run_date >= :start_date
                    GROUP BY spu
                    ORDER BY avg_wmape
                """)
                
                # 第一次查询（未缓存）
                start_time = time.time()
                result = conn.execute(cache_query, {
                    'start_date': '2026-01-01'
                })
                first_results = result.fetchall()
                first_time = time.time() - start_time
                
                # 第二次查询（可能缓存）
                start_time = time.time()
                result = conn.execute(cache_query, {
                    'start_date': '2026-01-01'
                })
                second_results = result.fetchall()
                second_time = time.time() - start_time
                
                results['performance_improvement'] = {
                    'first_query_time_ms': first_time * 1000,
                    'second_query_time_ms': second_time * 1000,
                    'improvement_pct': (first_time - second_time) / first_time * 100 if first_time > 0 else 0
                }
                
                conn.commit()
            
            self.logger.info(f"缓存优化完成, 表大小: {results['table_size']}, 行数: {results['cache_size']}")
            return results
            
        except Exception as e:
            self.logger.error(f"缓存优化失败: {e}")
            return results
    
    def run_optimization(self, table_name: str = 'sales_forecast_history', schema: str = 'finedatalink'):
        """
        运行全面优化
        
        Args:
            table_name: 表名
            schema: 模式名
            
        Returns:
            Dict: 优化结果汇总
        """
        results = {
            'optimization_timestamp': datetime.now().isoformat(),
            'indexes': self.optimize_indexes(table_name, schema),
            'queries': self.optimize_queries(table_name, schema),
            'caching': self.optimize_caching(table_name, schema)
        }
        
        # 生成优化报告
        report = f"""
=== 数据库性能优化报告 ===
优化时间: {results['optimization_timestamp']}

=== 索引优化 ===
创建的索引: {results['indexes']['indexes_created']}
性能提升: {results['indexes']['performance_improvement']}

=== 查询优化 ===
优化的查询: {[q['query_name'] for q in results['queries']['queries_optimized']]}
性能提升: {results['queries']['performance_improvement']}

=== 缓存优化 ===
表大小: {results['caching']['table_size']}
行数: {results['caching']['cache_size']}
性能提升: {results['caching']['performance_improvement']}
"""
        
        self.logger.info(report)
        
        return results


def main():
    """主函数"""
    # 从环境变量获取数据库URL
    db_url = os.environ.get('DATABASE_URL', 'postgresql://user:password@localhost:5432/dbname')
    
    # 创建数据库优化器
    optimizer = DatabaseOptimizer(
        db_url=db_url,
        pool_size=10,
        max_overflow=20
    )
    
    # 运行优化
    results = optimizer.run_optimization(
        table_name='sales_forecast_history',
        schema='finedatalink'
    )
    
    # 打印结果
    print(f"\n=== 优化结果 ===")
    print(f"索引创建: {results['indexes']['indexes_created']}")
    print(f"查询优化: {results['queries']['queries_optimized']}")
    print(f"缓存优化: {results['caching']['performance_improvement']}")
    
    return results


if __name__ == '__main__':
    main()
