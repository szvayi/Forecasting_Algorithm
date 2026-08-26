import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("检查数据库中实际存在的SPU...")

try:
    # 连接数据库
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # 直接查询数据库中存在的SPU
    print("\n查询数据库中存在的SPU...")
    query = """
    select
    case 
    when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
    when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
    when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
    else '-' end as SPU
    from lx_ods.查询订单利润_msku_cny_5年版
    group by SPU
    order by SPU
    """
    
    with engine.connect() as conn:
        spu_data = pd.read_sql(text(query), con=conn)
    
    print(f"✓ 查询成功: {len(spu_data)} 个SPU")
    print(f"✓ SPU列表: {spu_data['SPU'].tolist()}")
    
    # 检查我们需要的SPU是否存在
    expected_spus = [
        '2141', '2062', '2029', '2046', '2026', '3022', '1930', '2214', '2033', '2038',
        '2208', '2012', '3050', '2176', '3033', '2192', '2213', '3063', '2224', '3058',
        '2073', '3013', '2165', '3084', '1976', '2197', '1476', '1533', '887', '1577',
        '1750', '1512', '1657', '1983', '1318'
    ]
    
    existing_spus = spu_data['SPU'].tolist()
    found_spus = [spu for spu in expected_spus if spu in existing_spus]
    missing_spus = [spu for spu in expected_spus if spu not in existing_spus]
    
    print(f"\n预期SPU数量: {len(expected_spus)}")
    print(f"实际存在SPU数量: {len(found_spus)}")
    print(f"缺失SPU数量: {len(missing_spus)}")
    
    if found_spus:
        print(f"\n找到的SPU: {found_spus}")
    if missing_spus:
        print(f"\n缺失的SPU: {missing_spus}")
    
    engine.dispose()
    print("\n检查完成!")
    
except Exception as e:
    print(f"✗ 检查失败: {e}")
    import traceback
    traceback.print_exc()
