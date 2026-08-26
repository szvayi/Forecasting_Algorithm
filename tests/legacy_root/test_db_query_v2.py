import sys
sys.path.insert(0, '.')
import time

print("开始测试数据库查询...")

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink"

engine = create_engine(DB_URL, pool_pre_ping=True)

query = """
with base as (
    select
    a."date" as report_date,
    a.msku as local_sku,
    case 
    when substring(a.msku,1,5)='RHNWB' then substring(a.msku,6,4)
    when substring(a.msku,1,2)='VY' then substring(a.msku,5,4)
    when substring(a.msku,1,2)='WB' then substring(a.msku,3,4)
    else '-' end as SPU,
    sum(afn_amount+mfn_amount+promotion_discount+refund_amount+cost_of_points_granted+inventory_credit+shared_fba_liquidation_proceeds+shared_fba_liquidation_proceeds_adjustments
    +shared_amazon_shipping_reimbursement+shared_safe_t_reimbursement+shared_netco_transaction+shared_reimbursements+shared_clawbacks+shared_commingling_vat_income+giftWrapCredits
    +a_to_z_guarantee_claims+shared_others+shippingCost) as 销售额,
    sum(a.volume) as 销量,
    avg(avgNetAmount) as 平均售价,
    sum(ads_sd_cost+ads_sp_cost+ads_sb_cost+ads_sbv_cost) as 广告费
    from lx_ods.查询订单利润_msku_cny_5年版 a 
    left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
    group by 1,2,3
),
SPU_list as (
    SELECT '2141' AS SPU 
    UNION ALL 
    SELECT '2062'
)
select * from base
where SPU in (select SPU from SPU_list)
limit 10
"""

print("开始查询数据库...")
t0 = time.time()

try:
    with engine.connect() as conn:
        df = pd.read_sql(text(query), con=conn)
    
    print(f"查询成功! 耗时: {time.time() - t0:.2f}秒")
    print(f"返回 {len(df)} 行")
    print(df.head())
    
except Exception as e:
    print(f"查询失败: {e}")
    import traceback
    traceback.print_exc()

engine.dispose()
print("测试完成!")