import os
import pandas as pd
import json
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("评估SKU独立预测可行性...")

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
    
    # 分析SKU准确率
    print("\n分析SKU准确率...")
    
    # 提取SKU准确率数据
    sku_accuracy_data = []
    for _, row in df.iterrows():
        try:
            sku_accuracy = json.loads(row['sku_accuracy_json'])
            if isinstance(sku_accuracy, dict):
                for sku, info in sku_accuracy.items():
                    if isinstance(info, dict) and 'wmape' in info:
                        sku_accuracy_data.append({
                            'spu': row['spu'],
                            'sku': sku,
                            'wmape': info['wmape'] / 100,  # 转换为小数
                            'total_sales': info.get('total_sales', 0),
                            'weight_in_spu': info.get('weight_in_spu', 0),
                            'run_date': row['run_date'],
                            'forecast_target_date': row['forecast_target_date']
                        })
        except Exception as e:
            pass
    
    sku_df = pd.DataFrame(sku_accuracy_data)
    print(f"✓ 提取SKU准确率数据: {len(sku_df)} 条")
    
    if not sku_df.empty:
        # 分析SPU vs SKU准确率
        print("\n分析SPU vs SKU准确率差异...")
        
        # SPU平均准确率
        spu_accuracy = df.groupby('spu')['validation_wmape'].mean().reset_index()
        spu_accuracy.columns = ['spu', 'spu_wmape']
        
        # SKU平均准确率
        sku_accuracy = sku_df.groupby('spu')['wmape'].mean().reset_index()
        sku_accuracy.columns = ['spu', 'sku_wmape']
        
        # 合并分析
        accuracy_comparison = pd.merge(spu_accuracy, sku_accuracy, on='spu', how='left')
        accuracy_comparison['accuracy_diff'] = accuracy_comparison['spu_wmape'] - accuracy_comparison['sku_wmape']
        
        print("\nSPU vs SKU准确率对比:")
        print(accuracy_comparison)
        
        # 统计分析
        print("\n统计分析:")
        print(f"平均SPU准确率: {spu_accuracy['spu_wmape'].mean():.2%}")
        print(f"平均SKU准确率: {sku_accuracy['sku_wmape'].mean():.2%}")
        print(f"准确率差异: {accuracy_comparison['accuracy_diff'].mean():.2%}")
    
    # 分析SKU权重
    print("\n分析SKU权重...")
    
    def count_skus(row):
        try:
            sku_shares = json.loads(row['sku_share_json'])
            return len(sku_shares)
        except:
            return 0
    
    df['sku_count'] = df.apply(count_skus, axis=1)
    print(f"平均每个SPU的SKU数量: {df['sku_count'].mean():.1f}")
    
    # 生成落地方案
    print("\n生成SKU独立预测落地方案...")
    
    # 评估结论
    if not sku_df.empty:
        if 'accuracy_comparison' in locals() and not accuracy_comparison.empty:
            avg_diff = accuracy_comparison['accuracy_diff'].mean()
            if avg_diff > 0.05:
                conclusion = "SKU独立预测可能显著提高预测准确率"
                recommendation = "建议开展SKU独立预测"
            elif avg_diff > 0:
                conclusion = "SKU独立预测可能略微提高预测准确率"
                recommendation = "建议小规模试点SKU独立预测"
            else:
                conclusion = "SKU独立预测可能不会提高预测准确率"
                recommendation = "建议继续使用现有SPU预测方法"
        else:
            conclusion = "数据不足，无法评估准确率差异"
            recommendation = "建议收集更多数据后再评估"
    else:
        conclusion = "数据不足，无法评估"
        recommendation = "建议收集更多数据后再评估"
    
    # 落地方案
    landing_plan = f"""
    # SKU独立预测落地方案
    
    ## 1. 评估结论
    - {conclusion}
    - 分析SKU数量: {len(sku_df)} 条
    - 平均每个SPU的SKU数量: {df['sku_count'].mean():.1f}
    
    ## 2. 实施建议
    {recommendation}
    
    ## 3. 实施步骤
    1. **数据准备**：收集SKU级别的历史销售数据
    2. **模型适配**：将现有SPU预测逻辑适配到SKU级别
    3. **性能评估**：对少量SKU进行试点测试
    4. **规模推广**：根据试点结果决定是否全面推广
    5. **监控优化**：建立SKU预测准确率监控机制
    
    ## 4. 预期收益
    - 提高预测准确率，特别是对于SKU差异较大的SPU
    - 更精准的库存管理和补货决策
    - 更好的促销和定价策略支持
    
    ## 5. 风险评估
    - 计算资源需求增加（每个SKU都需要独立预测）
    - 数据质量要求更高（SKU级数据可能更稀疏）
    - 模型维护复杂度增加
    """
    
    # 保存落地方案
    with open('sku_forecast_landing_plan.txt', 'w', encoding='utf-8') as f:
        f.write(landing_plan)
    
    print("\n✓ SKU独立预测落地方案已生成: sku_forecast_landing_plan.txt")
    print("\n" + "=" * 70)
    print("评估完成!")
    print("=" * 70)
    
    engine.dispose()
    
except Exception as e:
    print(f"✗ 评估失败: {e}")
    import traceback
    traceback.print_exc()
