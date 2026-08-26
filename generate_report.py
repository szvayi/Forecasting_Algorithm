import os
import pandas as pd
import json
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")
DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")

print("生成预测效果HTML报告...")

try:
    # 连接数据库
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # 读取预测数据
    print("\n读取预测数据...")
    query = """
    SELECT * FROM finedatalink.sales_forecast_history
    ORDER BY run_date DESC, spu, forecast_target_date
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"✓ 读取成功: {len(df)} 条记录")
    print(f"✓ 唯一SPU数量: {df['spu'].nunique()}")
    
    # 分析数据
    print("\n分析数据...")
    
    # 按SPU分组分析
    spu_summary = df.groupby('spu').agg({
        'spu_forecast_value': ['mean', 'std'],
        'validation_wmape': 'mean'
    }).round(4)
    
    spu_summary.columns = ['平均预测值', '预测标准差', '平均WMAPE']
    spu_summary = spu_summary.reset_index()
    
    # 分析SKU权重
    def analyze_sku_shares(row):
        try:
            sku_shares = json.loads(row['sku_share_json'])
            return len(sku_shares), max(sku_shares.values())
        except:
            return 0, 0
    
    df[['sku_count', 'max_sku_share']] = df.apply(analyze_sku_shares, axis=1, result_type='expand')
    
    sku_summary = df.groupby('spu').agg({
        'sku_count': 'mean',
        'max_sku_share': 'mean'
    }).round(4)
    
    sku_summary.columns = ['平均SKU数量', '最大SKU占比']
    sku_summary = sku_summary.reset_index()
    
    # 合并分析结果
    analysis_result = pd.merge(spu_summary, sku_summary, on='spu', how='left')
    
    # 生成HTML报告
    print("\n生成HTML报告...")
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>销售预测效果分析报告</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ font-family: 'Microsoft YaHei', sans-serif; }}
            .summary-card {{ margin-bottom: 20px; }}
            .table-container {{ max-height: 400px; overflow-y: auto; }}
            .success {{ color: #198754; }}
            .warning {{ color: #ffc107; }}
            .danger {{ color: #dc3545; }}
        </style>
    </head>
    <body>
        <div class="container mt-4">
            <h1 class="text-center mb-4">销售预测效果分析报告</h1>
            
            <!-- 摘要信息 -->
            <div class="row mb-4">
                <div class="col-md-3">
                    <div class="card summary-card">
                        <div class="card-body">
                            <h5 class="card-title">预测SPU数量</h5>
                            <p class="card-text display-4">{df['spu'].nunique()}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card summary-card">
                        <div class="card-body">
                            <h5 class="card-title">预测记录数</h5>
                            <p class="card-text display-4">{len(df)}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card summary-card">
                        <div class="card-body">
                            <h5 class="card-title">平均WMAPE</h5>
                            <p class="card-text display-4">{df['validation_wmape'].mean():.2%}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card summary-card">
                        <div class="card-body">
                            <h5 class="card-title">最佳模型</h5>
                            <p class="card-text display-4">{df['winner_algo'].mode().iloc[0]}</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- SPU分析表格 -->
            <div class="mb-6">
                <h2>SPU预测效果分析</h2>
                <div class="table-container">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>SPU</th>
                                <th>平均预测值</th>
                                <th>预测标准差</th>
                                <th>平均WMAPE</th>
                                <th>平均SKU数量</th>
                                <th>最大SKU占比</th>
                            </tr>
                        </thead>
                        <tbody>
    """
    
    # 添加表格内容
    for _, row in analysis_result.iterrows():
        wmape_class = "success" if row['平均WMAPE'] < 0.1 else "warning" if row['平均WMAPE'] < 0.2 else "danger"
        html_content += f"""
                            <tr>
                                <td>{row['spu']}</td>
                                <td>{row['平均预测值']:.2f}</td>
                                <td>{row['预测标准差']:.2f}</td>
                                <td class="{wmape_class}">{row['平均WMAPE']:.2%}</td>
                                <td>{row['平均SKU数量']:.1f}</td>
                                <td>{row['最大SKU占比']:.2%}</td>
                            </tr>
        """
    
    html_content += f"""
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- 模型分布 -->
            <div class="mb-6">
                <h2>模型使用分布</h2>
                <div class="table-container">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>模型</th>
                                <th>使用次数</th>
                                <th>占比</th>
                                <th>平均WMAPE</th>
                            </tr>
                        </thead>
                        <tbody>
    """
    
    # 添加模型分布
    model_distribution = df.groupby('winner_algo').agg({
        'spu': 'count',
        'validation_wmape': 'mean'
    }).reset_index()
    model_distribution['占比'] = (model_distribution['spu'] / len(df) * 100).round(2)
    
    for _, row in model_distribution.iterrows():
        html_content += f"""
                            <tr>
                                <td>{row['winner_algo']}</td>
                                <td>{row['spu']}</td>
                                <td>{row['占比']:.2f}%</td>
                                <td>{row['validation_wmape']:.2%}</td>
                            </tr>
        """
    
    html_content += f"""
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- 预测趋势 -->
            <div class="mb-6">
                <h2>预测趋势概览</h2>
                <p>预测时间范围: {df['forecast_target_date'].min()} 至 {df['forecast_target_date'].max()}</p>
                <p>预测周数: {df['forecast_target_date'].nunique()} 周</p>
            </div>
            
            <!-- 结论与建议 -->
            <div class="mb-6">
                <h2>结论与建议</h2>
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">主要发现</h5>
                        <ul class="list-group list-group-flush">
                            <li class="list-group-item">• 共预测 {df['spu'].nunique()} 个SPU，覆盖未来 {df['forecast_target_date'].nunique()} 周</li>
                            <li class="list-group-item">• 平均预测准确率 (WMAPE): {df['validation_wmape'].mean():.2%}</li>
                            <li class="list-group-item">• 最常用模型: {df['winner_algo'].mode().iloc[0]}</li>
                            <li class="list-group-item">• 每个SPU平均包含 {df['sku_count'].mean():.1f} 个SKU</li>
                        </ul>
                    </div>
                </div>
            </div>
            
            <footer class="mt-6 text-center text-muted">
                <p>报告生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>数据来源: 销售预测系统</p>
            </footer>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    
    # 保存HTML报告到桌面
    report_path = os.path.join(DESKTOP_PATH, "销售预测效果分析报告.html")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ HTML报告已生成: {report_path}")
    print("\n报告已保存到桌面，请查收！")
    
    engine.dispose()
    
except Exception as e:
    print(f"✗ 生成报告失败: {e}")
    import traceback
    traceback.print_exc()
