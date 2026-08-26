import os
import pandas as pd
import json
import numpy as np
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("研究SKU权重改进方案...")

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
    
    # 分析SKU权重和准确率
    print("\n分析SKU权重和准确率...")
    
    # 提取SKU数据
    sku_data = []
    for _, row in df.iterrows():
        try:
            # 提取SKU准确率数据
            sku_accuracy = json.loads(row['sku_accuracy_json'])
            if isinstance(sku_accuracy, dict):
                for sku, info in sku_accuracy.items():
                    if isinstance(info, dict):
                        sku_data.append({
                            'spu': row['spu'],
                            'sku': sku,
                            'wmape': info.get('wmape', 0) / 100,  # 转换为小数
                            'total_sales': info.get('total_sales', 0),
                            'weight_in_spu': info.get('weight_in_spu', 0),
                            'run_date': row['run_date']
                        })
        except Exception as e:
            pass
    
    sku_df = pd.DataFrame(sku_data)
    print(f"✓ 提取SKU数据: {len(sku_df)} 条")
    
    if not sku_df.empty:
        # 分析权重与准确率的关系
        print("\n分析权重与准确率的关系...")
        
        # 按权重分组分析准确率
        sku_df['weight_group'] = pd.cut(sku_df['weight_in_spu'], 
                                       bins=[0, 0.01, 0.05, 0.1, 0.2, 1.0],
                                       labels=['<1%', '1-5%', '5-10%', '10-20%', '>20%'])
        
        weight_analysis = sku_df.groupby('weight_group').agg({
            'wmape': 'mean',
            'total_sales': 'mean',
            'weight_in_spu': 'mean',
            'sku': 'count'
        }).round(4)
        
        print("\n权重分组分析:")
        print(weight_analysis)
        
        # 分析误差较大的SKU
        print("\n分析误差较大的SKU...")
        high_error_skus = sku_df[sku_df['wmape'] > 0.1]  # 误差大于10%
        print(f"✓ 误差大于10%的SKU数量: {len(high_error_skus)}")
        print(f"✓ 占比: {len(high_error_skus)/len(sku_df)*100:.2f}%")
        
        if not high_error_skus.empty:
            print("\n高误差SKU的权重分布:")
            high_error_weight_analysis = high_error_skus.groupby('weight_group').agg({
                'sku': 'count',
                'wmape': 'mean'
            })
            print(high_error_weight_analysis)
    
    # 生成权重改进建议方案
    print("\n生成SKU权重改进建议方案...")
    
    # 基于分析结果提出改进建议
    improvement_suggestions = """
    # SKU权重改进建议方案
    
    ## 1. 当前权重问题分析
    - **问题识别**: 部分SKU通过权重方式出现较大误差
    - **数据基础**: 分析了 {len(sku_df)} 条SKU数据，覆盖 {df['spu'].nunique()} 个SPU
    - **误差分布**: {len(high_error_skus) if 'high_error_skus' in locals() else 0} 个SKU误差大于10%
    
    ## 2. 权重改进建议
    
    ### 2.1 动态权重调整策略
    1. **基于历史表现的权重调整**
       - 对预测准确率低的SKU降低初始权重
       - 对预测准确率高的SKU提高初始权重
       - 定期根据实际表现调整权重
    
    2. **销售规模加权**
       - 引入销售规模因子，对销售占比高的SKU给予更高权重
       - 避免小销量SKU的权重波动影响整体预测
    
    3. **时间衰减因子**
       - 最近期的销售数据权重更高
       - 远期数据权重逐渐降低
       - 适应市场变化和季节性需求
    
    ### 2.2 多维度权重计算
    1. **销售稳定性指标**
       - 计算SKU销售的波动率
       - 对销售稳定的SKU给予更高权重
       - 对销售波动大的SKU降低权重
    
    2. **季节性强度指标**
       - 分析SKU的季节性模式
       - 对季节性强的SKU使用更适合的权重计算方法
       - 对非季节性SKU使用稳定权重
    
    3. **产品生命周期阶段**
       - 识别新产品、成长产品、成熟产品和衰退产品
       - 为不同生命周期阶段的产品制定不同的权重策略
    
    ## 3. 实施步骤
    1. **数据准备**
       - 收集SKU级别的历史销售数据
       - 计算各SKU的销售稳定性、季节性等指标
    
    2. **模型调整**
       - 修改权重计算逻辑，引入多维度指标
       - 实现动态权重调整机制
    
    3. **测试验证**
       - 对改进后的权重策略进行离线测试
       - 与现有方法进行对比分析
    
    4. **规模推广**
       - 在少量SPU上进行试点
       - 根据试点结果调整参数
       - 全面推广改进后的权重策略
    
    ## 4. 预期效果
    - 降低SKU级预测误差，特别是高权重SKU
    - 提高整体预测准确率
    - 增强预测模型对市场变化的适应能力
    - 减少异常值对预测结果的影响
    
    ## 5. 监控与优化
    - 建立SKU权重监控机制
    - 定期评估权重策略的有效性
    - 根据实际表现持续优化权重计算方法
    """
    
    # 保存改进建议方案
    with open('sku_weight_improvement_plan.txt', 'w', encoding='utf-8') as f:
        f.write(improvement_suggestions)
    
    print("\n✓ SKU权重改进建议方案已生成: sku_weight_improvement_plan.txt")
    print("\n" + "=" * 70)
    print("研究完成!")
    print("=" * 70)
    
    engine.dispose()
    
except Exception as e:
    print(f"✗ 研究失败: {e}")
    import traceback
    traceback.print_exc()
