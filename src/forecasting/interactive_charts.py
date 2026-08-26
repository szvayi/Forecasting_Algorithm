"""
交互式图表增强模块
用于实现交互式图表功能
"""

import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd
import numpy as np

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("警告: plotly 未安装，使用 matplotlib 作为备选方案")

try:
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class InteractiveChartGenerator:
    """交互式图表生成器"""
    
    def __init__(self, save_dir: str = 'D:/华熠/plots'):
        """
        初始化交互式图表生成器
        
        Args:
            save_dir: 图表保存目录
        """
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)
        self.logger = logging.getLogger('forecasting')
        
        self.logger.info(f"InteractiveChartGenerator initialized, save_dir: {save_dir}")
    
    def generate_forecast_chart(self, profile, train, test, results, future, future_dates, 
                               sku_future_df=None, save_path=None, show_plot=True):
        """
        生成交互式预测图表
        
        Args:
            profile: 配置文件
            train: 训练数据
            test: 测试数据
            results: 模型结果
            future: 预测数据
            future_dates: 预测日期
            sku_future_df: SKU预测数据
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            go.Figure: Plotly图表对象
        """
        if not PLOTLY_AVAILABLE:
            self.logger.warning("Plotly未安装，使用matplotlib备选方案")
            return self._generate_matplotlib_chart(profile, train, test, results, future, 
                                                  future_dates, sku_future_df, save_path, show_plot)
        
        # 创建子图
        fig = make_subplots(rows=2, cols=1, 
                           subplot_titles=('销售预测', '模型性能对比'),
                           vertical_spacing=0.1,
                           specs=[[{"rowspan": 2}], [None]])
        
        # 添加历史数据
        fig.add_trace(
            go.Scatter(x=train.index, y=train.values, 
                      mode='lines', name='历史数据',
                      line=dict(color='gray', width=2)),
            row=1, col=1
        )
        
        # 添加实际值
        fig.add_trace(
            go.Scatter(x=test.index, y=test.values, 
                      mode='lines+markers', name='实际值',
                      line=dict(color='black', width=2),
                      marker=dict(size=6)),
            row=1, col=1
        )
        
        # 添加模型预测
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        for i, res in enumerate(results):
            fig.add_trace(
                go.Scatter(x=test.index, y=res['preds'], 
                          mode='lines+markers', name=f'{res["name"]} (WMAPE: {res["wmape"]:.2%})',
                          line=dict(color=colors[i % len(colors)], width=1.5),
                          marker=dict(size=4)),
                row=1, col=1
            )
        
        # 添加预测结果
        fig.add_trace(
            go.Scatter(x=future_dates, y=future, 
                      mode='lines+markers', name=f'{profile.winner_algo} 预测',
                      line=dict(color='purple', width=3),
                      marker=dict(size=6, symbol='diamond')),
            row=1, col=1
        )
        
        # 添加SKU预测
        if sku_future_df is not None and not sku_future_df.empty:
            top_skus = sku_future_df.sum().nlargest(5).index
            for i, sku in enumerate(top_skus):
                fig.add_trace(
                    go.Scatter(x=future_dates, y=sku_future_df[sku], 
                              mode='lines+markers', name=f'SKU {sku}',
                              line=dict(color=colors[(i + 1) % len(colors)], width=1.5, dash='dash'),
                              marker=dict(size=4)),
                    row=1, col=1
                )
        
        # 添加验证区间
        val_start = test.index[0]
        val_end = test.index[-1]
        fig.add_vrect(
            x0=val_start, x1=val_end,
            fillcolor="yellow", opacity=0.2,
            layer="below", line_width=0,
            row=1, col=1
        )
        
        # 添加预测区间
        pred_start = future_dates[0]
        pred_end = future_dates[-1]
        fig.add_vrect(
            x0=pred_start, x1=pred_end,
            fillcolor="green", opacity=0.2,
            layer="below", line_width=0,
            row=1, col=1
        )
        
        # 更新X轴
        fig.update_xaxes(title_text="日期", row=1, col=1)
        fig.update_yaxes(title_text="销量", row=1, col=1)
        
        # 添加模型性能对比图
        model_names = [r['name'] for r in results]
        wmapes = [r['wmape'] for r in results]
        winner_idx = model_names.index(profile.winner_algo)
        bar_colors = ['#1f77b4'] * len(model_names)
        bar_colors[winner_idx] = '#d62728'
        
        fig.add_trace(
            go.Bar(x=model_names, y=wmapes, 
                  marker_color=bar_colors,
                  text=[f'{w:.2%}' for w in wmapes],
                  textposition='auto'),
            row=2, col=1
        )
        
        # 更新布局
        fig.update_layout(
            title=f'SPU {profile.spu} 销售预测 - 胜出模型: {profile.winner_algo} (WMAPE: {profile.winner_wmape:.2%})',
            height=800,
            showlegend=True,
            legend=dict(x=1.02, y=1, xanchor='left'),
            hovermode='x unified'
        )
        
        # 更新X轴范围
        all_dates = pd.date_range(train.index[0], future_dates[-1], freq='W')
        fig.update_xaxes(range=[all_dates[0], all_dates[-1]], row=1, col=1)
        
        # 保存图表
        if save_path:
            fig.write_html(save_path.replace('.png', '.html'))
            self.logger.info(f"交互式图表已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            fig.show()
        
        return fig
    
    def _generate_matplotlib_chart(self, profile, train, test, results, future, future_dates,
                                  sku_future_df=None, save_path=None, show_plot=True):
        """
        生成matplotlib备选图表
        
        Args:
            profile: 配置文件
            train: 训练数据
            test: 测试数据
            results: 模型结果
            future: 预测数据
            future_dates: 预测日期
            sku_future_df: SKU预测数据
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: Matplotlib图表对象
        """
        if not MATPLOTLIB_AVAILABLE:
            self.logger.error("matplotlib未安装，无法生成图表")
            return None
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 1]})
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        
        # 添加历史数据
        ax1.plot(train.index, train.values, 'gray', label='历史数据', linewidth=2)
        
        # 添加实际值
        ax1.plot(test.index, test.values, 'k-', marker='o', label='实际值', linewidth=2, markersize=6)
        
        # 添加模型预测
        for i, res in enumerate(results):
            ax1.plot(test.index, res['preds'], colors[i % len(colors)], marker='s', 
                    label=f'{res["name"]} (WMAPE: {res["wmape"]:.2%})', linewidth=1.5, markersize=4)
        
        # 添加预测结果
        ax1.plot(future_dates, future, 'purple', marker='d', 
                label=f'{profile.winner_algo} 预测', linewidth=3, markersize=6)
        
        # 添加SKU预测
        if sku_future_df is not None and not sku_future_df.empty:
            top_skus = sku_future_df.sum().nlargest(5).index
            for i, sku in enumerate(top_skus):
                ax1.plot(future_dates, sku_future_df[sku], colors[(i + 1) % len(colors)], 
                        linestyle='--', marker='o', label=f'SKU {sku}', linewidth=1.5, markersize=4)
        
        # 添加验证区间
        val_start = test.index[0]
        val_end = test.index[-1]
        ax1.axvspan(val_start, val_end, alpha=0.2, color='yellow', label='验证区间')
        
        # 添加预测区间
        pred_start = future_dates[0]
        pred_end = future_dates[-1]
        ax1.axvspan(pred_start, pred_end, alpha=0.2, color='green', label='预测区间')
        
        # 设置标题和标签
        ax1.set_title(f'SPU {profile.spu} 销售预测 - 胜出模型: {profile.winner_algo} (WMAPE: {profile.winner_wmape:.2%})', fontsize=16)
        ax1.set_xlabel('日期', fontsize=12)
        ax1.set_ylabel('销量', fontsize=12)
        ax1.legend(loc='upper left', fontsize=10, bbox_to_anchor=(1, 1))
        ax1.grid(True, alpha=0.3)
        
        # 添加模型性能对比图
        model_names = [r['name'] for r in results]
        wmapes = [r['wmape'] for r in results]
        winner_idx = model_names.index(profile.winner_algo)
        bar_colors = ['#1f77b4'] * len(model_names)
        bar_colors[winner_idx] = '#d62728'
        
        ax2.bar(model_names, wmapes, color=bar_colors)
        ax2.set_title('模型 WMAPE 对比', fontsize=14)
        ax2.set_xlabel('模型', fontsize=12)
        ax2.set_ylabel('WMAPE', fontsize=12)
        for i, wmape in enumerate(wmapes):
            ax2.text(i, wmape, f'{wmape:.2%}', ha='center', va='bottom', fontsize=10)
        ax2.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        
        # 保存图表
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"图表已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            plt.show()
        
        plt.close()
        return fig
    
    def generate_sku_share_chart(self, sku_shares_df, save_path=None, show_plot=True):
        """
        生成SKU份额图表
        
        Args:
            sku_shares_df: SKU份额DataFrame
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            go.Figure: Plotly图表对象
        """
        if not PLOTLY_AVAILABLE:
            self.logger.warning("Plotly未安装，使用matplotlib备选方案")
            return self._generate_sku_share_matplotlib(sku_shares_df, save_path, show_plot)
        
        # 创建图表
        fig = go.Figure()
        
        # 添加每个SKU的份额
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
        
        for i, sku in enumerate(sku_shares_df.columns):
            fig.add_trace(
                go.Scatter(
                    x=sku_shares_df.index, 
                    y=sku_shares_df[sku],
                    mode='lines+markers',
                    name=f'SKU {sku}',
                    line=dict(color=colors[i % len(colors)], width=2),
                    marker=dict(size=4),
                    hovertemplate='<b>日期</b>: %{x}<br><b>份额</b>: %{y:.2%}<extra></extra>'
                )
            )
        
        # 更新布局
        fig.update_layout(
            title='SKU份额变化趋势',
            xaxis_title='日期',
            yaxis_title='份额',
            yaxis_tickformat='.0%',
            height=600,
            hovermode='x unified',
            legend=dict(x=1.02, y=1, xanchor='left')
        )
        
        # 保存图表
        if save_path:
            fig.write_html(save_path.replace('.png', '_sku_shares.html'))
            self.logger.info(f"SKU份额图表已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            fig.show()
        
        return fig
    
    def _generate_sku_share_matplotlib(self, sku_shares_df, save_path=None, show_plot=True):
        """
        生成matplotlib备选SKU份额图表
        
        Args:
            sku_shares_df: SKU份额DataFrame
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: Matplotlib图表对象
        """
        if not MATPLOTLIB_AVAILABLE:
            self.logger.error("matplotlib未安装，无法生成图表")
            return None
        
        fig, ax = plt.subplots(figsize=(14, 8))
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
        
        for i, sku in enumerate(sku_shares_df.columns):
            ax.plot(sku_shares_df.index, sku_shares_df[sku], 
                   color=colors[i % len(colors)], marker='o', 
                   label=f'SKU {sku}', linewidth=2, markersize=4)
        
        ax.set_title('SKU份额变化趋势', fontsize=16)
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('份额', fontsize=12)
        ax.yaxis.set_major_formatter plt.FuncFormatter(lambda y, _: '{:.0%}'.format(y))
        ax.legend(loc='upper left', bbox_to_anchor=(1, 1))
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # 保存图表
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"SKU份额图表已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            plt.show()
        
        plt.close()
        return fig
    
    def generate_wmape_trend_chart(self, wmape_history, save_path=None, show_plot=True):
        """
        生成WMAPE趋势图表
        
        Args:
            wmape_history: WMAPE历史数据
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            go.Figure: Plotly图表对象
        """
        if not PLOTLY_AVAILABLE:
            self.logger.warning("Plotly未安装，使用matplotlib备选方案")
            return self._generate_wmape_trend_matplotlib(wmape_history, save_path, show_plot)
        
        # 创建图表
        fig = go.Figure()
        
        # 添加WMAPE趋势
        fig.add_trace(
            go.Scatter(
                x=wmape_history['date'], 
                y=wmape_history['wmape'],
                mode='lines+markers',
                name='WMAPE',
                line=dict(color='#1f77b4', width=2),
                marker=dict(size=6),
                hovertemplate='<b>日期</b>: %{x}<br><b>WMAPE</b>: %{y:.2%}<extra></extra>'
            )
        )
        
        # 添加移动平均
        if len(wmape_history) >= 4:
            wmape_history = wmape_history.copy()
            wmape_history['ma4'] = wmape_history['wmape'].rolling(4).mean()
            
            fig.add_trace(
                go.Scatter(
                    x=wmape_history['date'], 
                    y=wmape_history['ma4'],
                    mode='lines',
                    name='4期移动平均',
                    line=dict(color='#ff7f0e', width=2, dash='dash'),
                    hovertemplate='<b>日期</b>: %{x}<br><b>MA4</b>: %{y:.2%}<extra></extra>'
                )
            )
        
        # 更新布局
        fig.update_layout(
            title='WMAPE趋势分析',
            xaxis_title='日期',
            yaxis_title='WMAPE',
            yaxis_tickformat='.0%',
            height=600,
            hovermode='x unified'
        )
        
        # 保存图表
        if save_path:
            fig.write_html(save_path.replace('.png', '_wmape_trend.html'))
            self.logger.info(f"WMAPE趋势图表已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            fig.show()
        
        return fig
    
    def _generate_wmape_trend_matplotlib(self, wmape_history, save_path=None, show_plot=True):
        """
        生成matplotlib备选WMAPE趋势图表
        
        Args:
            wmape_history: WMAPE历史数据
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: Matplotlib图表对象
        """
        if not MATPLOTLIB_AVAILABLE:
            self.logger.error("matplotlib未安装，无法生成图表")
            return None
        
        fig, ax = plt.subplots(figsize=(14, 8))
        
        ax.plot(wmape_history['date'], wmape_history['wmape'], 
               marker='o', label='WMAPE', linewidth=2, markersize=6)
        
        # 添加移动平均
        if len(wmape_history) >= 4:
            wmape_history = wmape_history.copy()
            wmape_history['ma4'] = wmape_history['wmape'].rolling(4).mean()
            ax.plot(wmape_history['date'], wmape_history['ma4'], 
                   linestyle='--', label='4期移动平均', linewidth=2)
        
        ax.set_title('WMAPE趋势分析', fontsize=16)
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('WMAPE', fontsize=12)
        ax.yaxis.set_major_formatter plt.FuncFormatter(lambda y, _: '{:.0%}'.format(y))
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # 保存图表
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"WMAPE趋势图表已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            plt.show()
        
        plt.close()
        return fig
    
    def generate_performance_dashboard(self, profile, train, test, results, future, future_dates,
                                      sku_future_df=None, wmape_history=None, save_path=None, 
                                      show_plot=True):
        """
        生成性能仪表盘
        
        Args:
            profile: 配置文件
            train: 训练数据
            test: 测试数据
            results: 模型结果
            future: 预测数据
            future_dates: 预测日期
            sku_future_df: SKU预测数据
            wmape_history: WMAPE历史数据
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            go.Figure: Plotly图表对象
        """
        if not PLOTLY_AVAILABLE:
            self.logger.warning("Plotly未安装，使用matplotlib备选方案")
            return self._generate_performance_dashboard_matplotlib(
                profile, train, test, results, future, future_dates, 
                sku_future_df, wmape_history, save_path, show_plot
            )
        
        # 创建子图
        if wmape_history is not None:
            fig = make_subplots(
                rows=3, cols=2,
                subplot_titles=('销售预测', '模型性能对比', 'SKU份额变化', 'WMAPE趋势', '预测区间', '历史数据'),
                specs=[[{"rowspan": 2}, {"rowspan": 2}],
                       [None, None],
                       [{"colspan": 2}, None]],
                vertical_spacing=0.08,
                horizontal_spacing=0.1
            )
        else:
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=('销售预测', '模型性能对比', 'SKU份额变化', '预测区间'),
                specs=[[{"rowspan": 2}, {"rowspan": 1}],
                       [None, {"rowspan": 1}]],
                vertical_spacing=0.1
            )
        
        # 添加销售预测图
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        
        fig.add_trace(
            go.Scatter(x=train.index, y=train.values, mode='lines', name='历史数据',
                      line=dict(color='gray', width=2)),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=test.index, y=test.values, mode='lines+markers', name='实际值',
                      line=dict(color='black', width=2), marker=dict(size=6)),
            row=1, col=1
        )
        
        for i, res in enumerate(results):
            fig.add_trace(
                go.Scatter(x=test.index, y=res['preds'], mode='lines+markers', 
                          name=f'{res["name"]} (WMAPE: {res["wmape"]:.2%})',
                          line=dict(color=colors[i % len(colors)], width=1.5),
                          marker=dict(size=4)),
                row=1, col=1
            )
        
        fig.add_trace(
            go.Scatter(x=future_dates, y=future, mode='lines+markers', 
                      name=f'{profile.winner_algo} 预测',
                      line=dict(color='purple', width=3), marker=dict(size=6, symbol='diamond')),
            row=1, col=1
        )
        
        if sku_future_df is not None and not sku_future_df.empty:
            top_skus = sku_future_df.sum().nlargest(5).index
            for i, sku in enumerate(top_skus):
                fig.add_trace(
                    go.Scatter(x=future_dates, y=sku_future_df[sku], mode='lines+markers', 
                              name=f'SKU {sku}',
                              line=dict(color=colors[(i + 1) % len(colors)], width=1.5, dash='dash'),
                              marker=dict(size=4)),
                    row=1, col=1
                )
        
        # 添加验证区间
        val_start = test.index[0]
        val_end = test.index[-1]
        fig.add_vrect(
            x0=val_start, x1=val_end,
            fillcolor="yellow", opacity=0.2,
            layer="below", line_width=0,
            row=1, col=1
        )
        
        # 添加预测区间
        pred_start = future_dates[0]
        pred_end = future_dates[-1]
        fig.add_vrect(
            x0=pred_start, x1=pred_end,
            fillcolor="green", opacity=0.2,
            layer="below", line_width=0,
            row=1, col=1
        )
        
        # 添加模型性能对比图
        model_names = [r['name'] for r in results]
        wmapes = [r['wmape'] for r in results]
        winner_idx = model_names.index(profile.winner_algo)
        bar_colors = ['#1f77b4'] * len(model_names)
        bar_colors[winner_idx] = '#d62728'
        
        fig.add_trace(
            go.Bar(x=model_names, y=wmapes, marker_color=bar_colors,
                  text=[f'{w:.2%}' for w in wmapes], textposition='auto'),
            row=1, col=2
        )
        
        # 添加SKU份额变化图
        if sku_future_df is not None and not sku_future_df.empty:
            for i, sku in enumerate(sku_future_df.columns[:5]):
                fig.add_trace(
                    go.Scatter(x=sku_future_df.index, y=sku_future_df[sku], 
                              mode='lines', name=f'SKU {sku}',
                              line=dict(color=colors[i % len(colors)], width=2)),
                    row=2, col=1
                )
        
        # 添加WMAPE趋势图
        if wmape_history is not None and len(wmape_history) > 0:
            fig.add_trace(
                go.Scatter(x=wmape_history['date'], y=wmape_history['wmape'], 
                          mode='lines+markers', name='WMAPE',
                          line=dict(color='#1f77b4', width=2), marker=dict(size=6)),
                row=2, col=1
            )
        
        # 更新布局
        fig.update_layout(
            title=f'SPU {profile.spu} 性能仪表盘 - 胜出模型: {profile.winner_algo} (WMAPE: {profile.winner_wmape:.2%})',
            height=1200,
            showlegend=True,
            legend=dict(x=1.02, y=1, xanchor='left'),
            hovermode='x unified'
        )
        
        # 保存图表
        if save_path:
            fig.write_html(save_path.replace('.png', '_dashboard.html'))
            self.logger.info(f"性能仪表盘已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            fig.show()
        
        return fig
    
    def _generate_performance_dashboard_matplotlib(self, profile, train, test, results, future, 
                                                  future_dates, sku_future_df=None, wmape_history=None,
                                                  save_path=None, show_plot=True):
        """
        生成matplotlib备选性能仪表盘
        
        Args:
            profile: 配置文件
            train: 训练数据
            test: 测试数据
            results: 模型结果
            future: 预测数据
            future_dates: 预测日期
            sku_future_df: SKU预测数据
            wmape_history: WMAPE历史数据
            save_path: 保存路径
            show_plot: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: Matplotlib图表对象
        """
        if not MATPLOTLIB_AVAILABLE:
            self.logger.error("matplotlib未安装，无法生成图表")
            return None
        
        if wmape_history is not None:
            fig, axes = plt.subplots(3, 2, figsize=(16, 14))
        else:
            fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        
        # 第一个子图：销售预测
        ax1 = axes[0, 0] if wmape_history is not None else axes[0, 0]
        ax1.plot(train.index, train.values, 'gray', label='历史数据', linewidth=2)
        ax1.plot(test.index, test.values, 'k-', marker='o', label='实际值', linewidth=2, markersize=6)
        
        for i, res in enumerate(results):
            ax1.plot(test.index, res['preds'], colors[i % len(colors)], marker='s', 
                    label=f'{res["name"]} (WMAPE: {res["wmape"]:.2%})', linewidth=1.5, markersize=4)
        
        ax1.plot(future_dates, future, 'purple', marker='d', 
                label=f'{profile.winner_algo} 预测', linewidth=3, markersize=6)
        
        if sku_future_df is not None and not sku_future_df.empty:
            top_skus = sku_future_df.sum().nlargest(5).index
            for i, sku in enumerate(top_skus):
                ax1.plot(future_dates, sku_future_df[sku], colors[(i + 1) % len(colors)], 
                        linestyle='--', marker='o', label=f'SKU {sku}', linewidth=1.5, markersize=4)
        
        val_start = test.index[0]
        val_end = test.index[-1]
        ax1.axvspan(val_start, val_end, alpha=0.2, color='yellow', label='验证区间')
        
        pred_start = future_dates[0]
        pred_end = future_dates[-1]
        ax1.axvspan(pred_start, pred_end, alpha=0.2, color='green', label='预测区间')
        
        ax1.set_title(f'SPU {profile.spu} 销售预测', fontsize=14)
        ax1.set_xlabel('日期', fontsize=10)
        ax1.set_ylabel('销量', fontsize=10)
        ax1.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=8)
        ax1.grid(True, alpha=0.3)
        
        # 第二个子图：模型性能对比
        ax2 = axes[0, 1] if wmape_history is not None else axes[0, 1]
        model_names = [r['name'] for r in results]
        wmapes = [r['wmape'] for r in results]
        winner_idx = model_names.index(profile.winner_algo)
        bar_colors = ['#1f77b4'] * len(model_names)
        bar_colors[winner_idx] = '#d62728'
        
        ax2.bar(model_names, wmapes, color=bar_colors)
        ax2.set_title('模型 WMAPE 对比', fontsize=14)
        ax2.set_xlabel('模型', fontsize=10)
        ax2.set_ylabel('WMAPE', fontsize=10)
        ax2.yaxis.set_major_formatter plt.FuncFormatter(lambda y, _: '{:.0%}'.format(y))
        for i, wmape in enumerate(wmapes):
            ax2.text(i, wmape, f'{wmape:.2%}', ha='center', va='bottom', fontsize=8)
        ax2.grid(True, alpha=0.3, axis='y')
        
        # 第三个子图：SKU份额变化
        if sku_future_df is not None and not sku_future_df.empty:
            ax3 = axes[1, 0] if wmape_history is not None else axes[1, 0]
            for i, sku in enumerate(sku_future_df.columns[:5]):
                ax3.plot(sku_future_df.index, sku_future_df[sku], 
                        color=colors[i % len(colors)], marker='o', 
                        label=f'SKU {sku}', linewidth=2, markersize=4)
            
            ax3.set_title('SKU份额变化趋势', fontsize=14)
            ax3.set_xlabel('日期', fontsize=10)
            ax3.set_ylabel('份额', fontsize=10)
            ax3.yaxis.set_major_formatter plt.FuncFormatter(lambda y, _: '{:.0%}'.format(y))
            ax3.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=8)
            ax3.grid(True, alpha=0.3)
        
        # 第四个子图：WMAPE趋势
        if wmape_history is not None and len(wmape_history) > 0:
            ax4 = axes[1, 1] if wmape_history is not None else axes[1, 0]
            ax4.plot(wmape_history['date'], wmape_history['wmape'], 
                   marker='o', label='WMAPE', linewidth=2, markersize=6)
            
            if len(wmape_history) >= 4:
                wmape_history = wmape_history.copy()
                wmape_history['ma4'] = wmape_history['wmape'].rolling(4).mean()
                ax4.plot(wmape_history['date'], wmape_history['ma4'], 
                       linestyle='--', label='4期移动平均', linewidth=2)
            
            ax4.set_title('WMAPE趋势分析', fontsize=14)
            ax4.set_xlabel('日期', fontsize=10)
            ax4.set_ylabel('WMAPE', fontsize=10)
            ax4.yaxis.set_major_formatter plt.FuncFormatter(lambda y, _: '{:.0%}'.format(y))
            ax4.legend()
            ax4.grid(True, alpha=0.3)
        
        plt.suptitle(f'SPU {profile.spu} 性能仪表盘 - 胜出模型: {profile.winner_algo} (WMAPE: {profile.winner_wmape:.2%})', 
                    fontsize=16, y=0.98)
        
        plt.tight_layout()
        
        # 保存图表
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"性能仪表盘已保存至: {save_path}")
        
        # 显示图表
        if show_plot:
            plt.show()
        
        plt.close()
        return fig


def main():
    """主函数"""
    # 生成示例数据
    dates = pd.date_range('2026-01-01', periods=100, freq='W')
    
    # 训练数据
    train = pd.Series(np.random.randint(100, 1000, 80), index=dates[:80])
    
    # 测试数据
    test = pd.Series(np.random.randint(100, 1000, 10), index=dates[80:90])
    
    # 预测数据
    future = np.random.randint(100, 1000, 10)
    future_dates = dates[90:100]
    
    # 模型结果
    results = [
        {'name': 'Prophet', 'wmape': 0.15, 'preds': np.random.randint(100, 1000, 10)},
        {'name': 'XGBoost', 'wmape': 0.18, 'preds': np.random.randint(100, 1000, 10)},
        {'name': 'LightGBM', 'wmape': 0.16, 'preds': np.random.randint(100, 1000, 10)}
    ]
    
    # SKU预测数据
    sku_future_df = pd.DataFrame({
        'SKU001': np.random.randint(10, 100, 10),
        'SKU002': np.random.randint(20, 200, 10),
        'SKU003': np.random.randint(15, 150, 10)
    }, index=future_dates)
    
    # 生成图表
    generator = InteractiveChartGenerator(save_dir='D:/华熠/plots')
    
    # 生成销售预测图表
    fig1 = generator.generate_forecast_chart(
        profile=None, train=train, test=test, results=results, 
        future=future, future_dates=future_dates, sku_future_df=sku_future_df,
        save_path='D:/华熠/plots/test_forecast.html', show_plot=False
    )
    
    # 生成SKU份额图表
    fig2 = generator.generate_sku_share_chart(
        sku_shares_df=sku_future_df, 
        save_path='D:/华熠/plots/test_sku_shares.html', 
        show_plot=False
    )
    
    # 生成WMAPE趋势图表
    wmape_history = pd.DataFrame({
        'date': dates[80:100],
        'wmape': np.random.uniform(0.1, 0.3, 20)
    })
    fig3 = generator.generate_wmape_trend_chart(
        wmape_history=wmape_history,
        save_path='D:/华熠/plots/test_wmape_trend.html',
        show_plot=False
    )
    
    return generator


if __name__ == '__main__':
    main()
