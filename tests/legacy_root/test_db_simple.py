import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv("SALES_FORECAST_DB_URL", "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink")

print("测试数据库连接和数据获取...")

try:
    # 测试数据库连接
    engine = create_engine(DB_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print(f"✓ 数据库连接成功: {result.fetchone()}")
    
    # 测试完整的查询
    print("\n测试完整查询...")
    query = """
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
    )
    select report_date as date, sum(销量) as sales, SPU as spu, local_sku as sku,
           ROUND(SUM(-广告费)::NUMERIC, 2) as ad_cost, avg(平均售价) as price
    from base 
    where 1=1 and SPU in (select SPU from SPU_list)
    group by report_date, SPU, local_sku
    order by report_date
    limit 10
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"✓ 查询成功: {len(df)} 行")
    print(f"✓ 列名: {df.columns.tolist()}")
    print(f"✓ 数据预览:\n{df.head()}")
    
    engine.dispose()
    print("\n测试成功!")
    
except Exception as e:
    print(f"✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
