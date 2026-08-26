import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("测试SQL查询返回的SPU数据...")

try:
    # 连接数据库
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # 测试SPU_list查询
    print("\n测试SPU_list查询...")
    spu_list_query = """
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
    SELECT '0887' 
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
    """
    
    with engine.connect() as conn:
        spu_list = pd.read_sql(text(spu_list_query), con=conn)
    print(f"✓ SPU_list查询成功: {len(spu_list)} 个SPU")
    
    # 测试基础数据查询（限制返回100行）
    print("\n测试基础数据查询...")
    base_query = """
    select
    a."date" as report_date,
    local_sku,
    case 
    when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
    when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
    when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
    else '-' end as SPU,
    sum(afn_amount+mfn_amount+promotion_discount+refund_amount+cost_of_points_granted+inventory_credit+shared_fba_liquidation_proceeds+shared_fba_liquidation_proceeds_adjustments
    +shared_amazon_shipping_reimbursement+shared_safe_t_reimbursement+shared_netco_transaction+shared_reimbursements+shared_clawbacks+shared_commingling_vat_income+gift_wrap_credits
    +a_to_z_guarantee_claims+shared_others+shipping_cost) as 销售额,
    sum(a.volume) as 销量,
    avg(avg_net_amount) as 平均售价,
    sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费
    from lx_ods.查询订单利润_msku_cny_5年版 a 
    left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
    where 1=1
    group by 1,2,3
    limit 100
    """
    
    with engine.connect() as conn:
        base_data = pd.read_sql(text(base_query), con=conn)
    print(f"✓ 基础数据查询成功: {len(base_data)} 行")
    print(f"✓ 唯一SPU数量: {base_data['SPU'].nunique()}")
    print(f"✓ SPU列表: {base_data['SPU'].unique()}")
    
    # 测试完整查询（限制返回100行）
    print("\n测试完整查询...")
    full_query = """
    with base as (
        select
        a."date" as report_date,
        local_sku,
        case 
        when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
        when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
        when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
        else '-' end as SPU,
        sum(afn_amount+mfn_amount+promotion_discount+refund_amount+cost_of_points_granted+inventory_credit+shared_fba_liquidation_proceeds+shared_fba_liquidation_proceeds_adjustments
        +shared_amazon_shipping_reimbursement+shared_safe_t_reimbursement+shared_netco_transaction+shared_reimbursements+shared_clawbacks+shared_commingling_vat_income+gift_wrap_credits
        +a_to_z_guarantee_claims+shared_others+shipping_cost) as 销售额,
        sum(a.volume) as 销量,
        avg(avg_net_amount) as 平均售价,
        sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        group by 1,2,3
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
        SELECT '0887' 
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
    order by report_date
    limit 100
    """
    
    with engine.connect() as conn:
        full_data = pd.read_sql(text(full_query), con=conn)
    print(f"✓ 完整查询成功: {len(full_data)} 行")
    print(f"✓ 唯一SPU数量: {full_data['spu'].nunique()}")
    print(f"✓ SPU列表: {full_data['spu'].unique()}")
    
    engine.dispose()
    print("\n测试完成!")
    
except Exception as e:
    print(f"✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
