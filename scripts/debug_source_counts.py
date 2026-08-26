import os
from sqlalchemy import create_engine, text

def main():
    db_url = os.getenv("SALES_FORECAST_DB_URL")
    if not db_url:
        raise RuntimeError("缺少环境变量 SALES_FORECAST_DB_URL")

    spu_list_env = os.getenv("SPU_LIST", "").strip()
    spu_filter_sql = ""
    if spu_list_env:
        tokens = [s.strip() for s in spu_list_env.split(",") if s.strip()]
        if tokens:
            in_list = ",".join([f"'{t}'" for t in tokens])
            spu_filter_sql = f" and SPU in ({in_list})"

    query = f"""
    with base as (
        select
        a."date" as report_date,
        local_sku,
        case 
        when substring(local_sku,1,5)='RHNWB' then substring(local_sku,6,4)
        when substring(local_sku,1,2)='VY' then substring(local_sku,5,4)
        when substring(local_sku,1,2)='WB' then substring(local_sku,3,4)
        else '-' end as SPU,
        sum(a.volume) as 销量
        from lx_ods.查询订单利润_msku_cny_5年版 a 
        left join lx_ods.查询订单利润_msku_cny_商品基础信息_5年版 b on a.__dm_key=b.__dm_key
        group by 1,2,3
    )
    select SPU, count(distinct report_date) as days, 
           count(*) as rows, 
           min(report_date) as min_date,
           max(report_date) as max_date
    from base
    where 1=1{spu_filter_sql}
    group by SPU
    order by SPU
    """
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(query)).fetchall()
            print("源数据统计（按 SPU）:")
            for r in rows:
                print(f"  SPU={r[0]} days={r[1]} rows={r[2]} range={r[3]}~{r[4]}")
    finally:
        engine.dispose()

if __name__ == "__main__":
    main()

