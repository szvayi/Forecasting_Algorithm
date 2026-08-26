import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

# 输出文件
output_file = "spu_data_check.txt"

print(f"检查数据库中的SPU数据，结果将保存到: {output_file}")

try:
    # 连接数据库
    engine = create_engine(DB_URL, pool_pre_ping=True)
    print("✓ 数据库连接成功")
    
    # 测试获取数据
    print("测试获取数据...")
    
    # 直接执行SQL查询
    query = """
    with base as (
        select report_date,local_sku,销量,广告费,平均售价,
        case 
        when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
        when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
        when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
        else '-' end as SPU
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        group by 1,2,3,4,5
    ),
    SPU_list as (
        SELECT '2141' AS SPU 
        UNION ALL 
        SELECT '2062' 
        UNION ALL 
        SELECT '2029' 
        UNION ALL 
        SELECT '2046' 
        UNION ALL 
        SELECT '2026' 
        UNION ALL 
        SELECT '3022' 
        UNION ALL 
        SELECT '1930' 
        UNION ALL 
        SELECT '2214' 
        UNION ALL 
        SELECT '2033' 
        UNION ALL 
        SELECT '2038' 
        UNION ALL 
        SELECT '2208' 
        UNION ALL 
        SELECT '2012' 
        UNION ALL 
        SELECT '3050' 
        UNION ALL 
        SELECT '2176' 
        UNION ALL 
        SELECT '3033' 
        UNION ALL 
        SELECT '2192' 
        UNION ALL 
        SELECT '2213' 
        UNION ALL 
        SELECT '3063' 
        UNION ALL 
        SELECT '2224' 
        UNION ALL 
        SELECT '3058' 
        UNION ALL 
        SELECT '2073' 
        UNION ALL 
        SELECT '3013' 
        UNION ALL 
        SELECT '2165' 
        UNION ALL 
        SELECT '3084' 
        UNION ALL 
        SELECT '1976' 
        UNION ALL 
        SELECT '2197' 
        UNION ALL 
        SELECT '1476' 
        UNION ALL 
        SELECT '1533' 
        UNION ALL 
        SELECT '887' 
        UNION ALL 
        SELECT '1577' 
        UNION ALL 
        SELECT '1750' 
        UNION ALL 
        SELECT '1512' 
        UNION ALL 
        SELECT '1657' 
        UNION ALL 
        SELECT '1983' 
        UNION ALL 
        SELECT '1318' 
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
    from base 
    where 1=1 and SPU in (select SPU from SPU_list)
    group by report_date, SPU, local_sku
    order by SPU, report_date
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    # 统计SPU数量
    spus = df['spu'].unique()
    spu_count = len(spus)
    
    # 写入结果到文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"检查时间: {pd.Timestamp.now()}\n")
        f.write(f"总记录数: {len(df)}\n")
        f.write(f"SPU数量: {spu_count}\n")
        f.write("SPU列表:\n")
        for spu in sorted(spus):
            spu_records = len(df[df['spu'] == spu])
            f.write(f"- {spu}: {spu_records} 条记录\n")
        
        f.write("\n前10条记录:\n")
        f.write(df.head(10).to_string(index=False))
    
    print(f"✓ 检查完成，结果已保存到: {output_file}")
    print(f"✓ 发现 {spu_count} 个SPU")
    print(f"✓ SPU列表: {sorted(spus)}")
    
    engine.dispose()
    
except Exception as e:
    print(f"✗ 检查失败: {e}")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"检查失败: {e}\n")
    import traceback
    traceback.print_exc()
