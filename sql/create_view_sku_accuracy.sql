CREATE OR REPLACE VIEW finedatalink.v_spu_sku_accuracy_detail AS
WITH expanded AS (
    SELECT
        spu,
        run_date,
        winner_algo,
        validation_wmape as spu_validation_wmape,
        -- Explicitly cast to text then to json to handle both types
        -- This avoids the CASE type mismatch error in Postgres
        sku_accuracy_json::text::json as sku_json_obj
    FROM
        finedatalink.sales_forecast_history
    WHERE
        sku_accuracy_json IS NOT NULL
        AND sku_accuracy_json::text != 'null'
)
SELECT
    expanded.spu,
    expanded.run_date,
    expanded.winner_algo,
    expanded.spu_validation_wmape,
    key as sku,
    CAST(value->>'wmape' AS NUMERIC) as sku_wmape,
    CAST(value->>'weight_in_spu' AS NUMERIC) as sku_weight_in_spu,
    CAST(value->>'total_sales' AS NUMERIC) as sku_total_sales
FROM
    expanded,
    json_each(sku_json_obj);

COMMENT ON VIEW finedatalink.v_spu_sku_accuracy_detail IS 'View for SPU vs SKU WMAPE comparison, expanded from sku_accuracy_json';
